import json
import logging
import os
from typing import Annotated

import redis as redis_lib
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from auth import get_current_user, require_doctor
from database import Base, engine, get_db
from llm import assess_checkin_urgency, generate_care_plan
from logging_utils import write_structured_log
from models import AuditLog, CarePlan, Escalation, FollowupCheckin, Patient
from schemas import CarePlanCreate, CarePlanResponse, CheckinCreate, CheckinResponse, EscalationResponse
from settings import settings

logger = logging.getLogger(__name__)

_TESTING = os.getenv("TESTING", "false").lower() == "true"

app = FastAPI(title="PostCare API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

router = APIRouter(prefix="/v1")

if not _TESTING:
    from database import engine as _engine
    from telemetry import setup_telemetry
    setup_telemetry("postcare_api", app=app, db_engine=_engine)


@app.on_event("startup")
def on_startup() -> None:
    if _TESTING:
        return
    Base.metadata.create_all(bind=engine)


def _get_redis():
    try:
        r = redis_lib.from_url(settings.REDIS_URL, decode_responses=True, socket_connect_timeout=2)
        r.ping()
        return r
    except Exception:
        return None


def _write_audit(db: Session, route: str, action: str, outcome: str, actor_id=None, patient_id=None, ip=None):
    try:
        entry = AuditLog(service="postcare_api", route=route, actor_id=actor_id, patient_id=patient_id, action=action, outcome=outcome, ip_address=ip)
        db.add(entry)
        db.commit()
    except Exception:
        db.rollback()


def _require_internal_key(x_internal_key: Annotated[str | None, Header()] = None):
    if x_internal_key != settings.INTERNAL_API_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")


@router.post("/careplan/generate", response_model=CarePlanResponse, status_code=201)
async def create_care_plan(
    body: CarePlanCreate,
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(_require_internal_key),
):
    plan_data = await generate_care_plan(body.patient_id, body.visit_notes)

    try:
        from datetime import date
        follow_up = None
        if plan_data.get("follow_up_date"):
            try:
                follow_up = date.fromisoformat(plan_data["follow_up_date"])
            except (ValueError, TypeError):
                follow_up = None

        plan = CarePlan(
            patient_id=body.patient_id,
            follow_up_date=follow_up,
            medications_to_monitor=plan_data.get("medications_to_monitor", []),
            lifestyle_recommendations=plan_data.get("lifestyle_recommendations", []),
            warning_signs=plan_data.get("warning_signs", []),
            visit_notes=body.visit_notes,
        )
        db.add(plan)
        db.commit()
        db.refresh(plan)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="Database unavailable") from exc

    _write_audit(db, "/v1/careplan/generate", "careplan_generate", "success", patient_id=body.patient_id, ip=request.client.host if request.client else None)
    write_structured_log("/v1/careplan/generate", "careplan_generate", "success", request, patient_id=body.patient_id)
    return CarePlanResponse.model_validate(plan)


@router.get("/careplan/{patient_id}", response_model=CarePlanResponse)
def get_care_plan(
    patient_id: str,
    request: Request,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.get("role") != "doctor" and user.get("sub") != patient_id:
        raise HTTPException(status_code=403, detail="Access denied")

    try:
        plan = (
            db.query(CarePlan)
            .filter(CarePlan.patient_id == patient_id)
            .order_by(CarePlan.created_at.desc())
            .first()
        )
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc

    if not plan:
        raise HTTPException(status_code=404, detail="No care plan found for this patient")

    _write_audit(db, f"/v1/careplan/{patient_id}", "careplan_read", "success", actor_id=user.get("sub"), patient_id=patient_id, ip=request.client.host if request.client else None)
    write_structured_log(f"/v1/careplan/{patient_id}", "careplan_read", "success", request, user.get("sub"), patient_id)
    return CarePlanResponse.model_validate(plan)


@router.post("/followup/checkin", response_model=CheckinResponse, status_code=201)
async def checkin(
    body: CheckinCreate,
    request: Request,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.get("role") != "doctor" and user.get("sub") != str(body.patient_id):
        raise HTTPException(status_code=403, detail="Access denied")

    latest_plan = (
        db.query(CarePlan)
        .filter(CarePlan.patient_id == body.patient_id)
        .order_by(CarePlan.created_at.desc())
        .first()
    )
    care_plan_dict = {}
    if latest_plan:
        care_plan_dict = {
            "warning_signs": latest_plan.warning_signs or [],
            "medications_to_monitor": latest_plan.medications_to_monitor or [],
        }

    urgency_result = await assess_checkin_urgency(body.symptom_report, care_plan_dict)

    try:
        checkin_record = FollowupCheckin(
            patient_id=body.patient_id,
            symptom_report=body.symptom_report,
            urgency=urgency_result.get("urgency", "routine"),
            reason=urgency_result.get("reason", ""),
        )
        db.add(checkin_record)
        db.commit()
        db.refresh(checkin_record)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="Database unavailable") from exc

    if urgency_result.get("urgency") == "escalate":
        try:
            escalation = Escalation(
                checkin_id=checkin_record.id,
                patient_id=body.patient_id,
                acknowledged=False,
            )
            db.add(escalation)
            db.commit()
        except SQLAlchemyError:
            db.rollback()

        redis = _get_redis()
        if redis:
            try:
                redis.lpush("escalation_queue", json.dumps({
                    "patient_id": body.patient_id,
                    "checkin_id": str(checkin_record.id),
                    "urgency": urgency_result.get("urgency"),
                    "reason": urgency_result.get("reason"),
                }))
            except Exception as exc:
                logger.warning("Redis escalation queue push failed: %s", exc)

    _write_audit(db, "/v1/followup/checkin", "checkin_submit", "success", actor_id=user.get("sub"), patient_id=body.patient_id, ip=request.client.host if request.client else None)
    write_structured_log("/v1/followup/checkin", "checkin_submit", "success", request, user.get("sub"), body.patient_id)
    return CheckinResponse.model_validate(checkin_record)


@router.get("/escalations/pending")
def pending_escalations(
    request: Request,
    user: dict = Depends(require_doctor),
    db: Session = Depends(get_db),
):
    try:
        escalations = db.query(Escalation).filter(Escalation.acknowledged == False).all()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return [EscalationResponse.model_validate(e) for e in escalations]


@router.post("/escalations/{escalation_id}/acknowledge")
def acknowledge_escalation(
    escalation_id: str,
    request: Request,
    user: dict = Depends(require_doctor),
    db: Session = Depends(get_db),
):
    escalation = db.query(Escalation).filter(Escalation.id == escalation_id).first()
    if not escalation:
        raise HTTPException(status_code=404, detail="Escalation not found")
    try:
        escalation.acknowledged = True
        escalation.acknowledged_by = user.get("sub")
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="Database unavailable") from exc

    _write_audit(db, f"/v1/escalations/{escalation_id}/acknowledge", "escalation_acknowledged", "success", actor_id=user.get("sub"), ip=request.client.host if request.client else None)
    return {"status": "acknowledged"}


app.include_router(router)


@app.get("/health")
def health(db: Session = Depends(get_db)):
    details: dict = {}
    degraded = False

    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        details["postgres"] = str(exc)
        degraded = True

    try:
        r = redis_lib.from_url(settings.REDIS_URL, socket_connect_timeout=2)
        r.ping()
    except Exception as exc:
        details["redis"] = str(exc)
        degraded = True

    if degraded:
        return {"status": "degraded", "details": details}
    return {"status": "ok"}
