import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Annotated

import redis as redis_lib
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from passlib.context import CryptContext
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from auth import create_access_token, get_current_doctor
from database import Base, SessionLocal, engine, get_db
from encryption import decrypt
from llm import get_risk_assessment
from logging_utils import write_structured_log
from models import AuditLog, Doctor, Escalation, FollowupCheckin, Patient, PatientIntake, RiskAssessment, Feedback
from schemas import DoctorRegister, FeedbackCreate, LoginResponse, PatientListItem, RiskAssessmentResponse
from settings import settings

from agent.router import agent_router

logger = logging.getLogger(__name__)

_TESTING = os.getenv("TESTING", "false").lower() == "true"
_AUTH_RATE_LIMIT = "1000/minute" if _TESTING else "5/minute"

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Doctor API", version="1.0.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
RETRAIN_BUFFER = Path("/app/data/retrain_buffer.jsonl")
router = APIRouter(prefix="/v1")


@app.on_event("startup")
def on_startup() -> None:
    if _TESTING:
        return
    Base.metadata.create_all(bind=engine)
    RETRAIN_BUFFER.parent.mkdir(parents=True, exist_ok=True)
    db = SessionLocal()
    try:
        if not db.query(Doctor).filter(Doctor.email == "doctor@demo.com").first():
            demo = Doctor(
                email="doctor@demo.com",
                hashed_password=pwd_context.hash("demo1234"),
                name="Dr. Demo",
                specialty="General Practice",
            )
            db.add(demo)
            db.commit()
    except Exception as exc:
        logger.warning("Could not seed demo doctor: %s", exc)
        db.rollback()
    finally:
        db.close()


def _get_redis():
    try:
        r = redis_lib.from_url(settings.REDIS_URL, decode_responses=True, socket_connect_timeout=2)
        r.ping()
        return r
    except Exception:
        return None


def _write_audit(db: Session, route: str, action: str, outcome: str, actor_id=None, patient_id=None, ip=None):
    try:
        entry = AuditLog(service="doctor_api", route=route, actor_id=actor_id, patient_id=patient_id, action=action, outcome=outcome, ip_address=ip)
        db.add(entry)
        db.commit()
    except Exception:
        db.rollback()


def _set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key="doctor_access_token",
        value=token,
        httponly=True,
        max_age=settings.JWT_EXPIRE_MINUTES * 60,
        path="/",
        domain="localhost",
        samesite="none",
        secure=True,
    )


@router.post("/auth/register", status_code=201)
def register_doctor(body: DoctorRegister, db: Session = Depends(get_db)):
    if db.query(Doctor).filter(Doctor.email == body.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    try:
        doctor = Doctor(
            email=body.email,
            hashed_password=pwd_context.hash(body.password),
            name=body.name,
            specialty=body.specialty,
        )
        db.add(doctor)
        db.commit()
        db.refresh(doctor)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {"message": "registered", "doctor_id": str(doctor.id)}


@router.post("/auth/token", response_model=LoginResponse)
@limiter.limit(_AUTH_RATE_LIMIT)
def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    doctor = db.query(Doctor).filter(Doctor.email == form.username).first()
    if not doctor or not pwd_context.verify(form.password, doctor.hashed_password):
        write_structured_log("/v1/auth/token", "login", "failed", request)
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token({"sub": str(doctor.id)})
    _set_auth_cookie(response, token)
    write_structured_log("/v1/auth/token", "login", "success", request, str(doctor.id))
    return LoginResponse(doctor_id=str(doctor.id))


@router.post("/auth/logout")
def logout(response: Response):
    response.delete_cookie(
        key="doctor_access_token",
        path="/",
        domain="localhost",
        samesite="none",
        secure=True,
    )
    return {"status": "logged out"}


@router.get("/doctor/patients")
def list_patients(
    request: Request,
    current_doctor: Doctor = Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    try:
        patients = db.query(Patient).all()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc

    result = []
    for p in patients:
        intake = db.query(PatientIntake).filter(PatientIntake.patient_id == p.id).order_by(PatientIntake.submitted_at.desc()).first()
        result.append(PatientListItem(
            id=p.id,
            name=p.name or "",
            email=p.email or "",
            intake_submitted_at=intake.submitted_at if intake else None,
        ))

    write_structured_log("/v1/doctor/patients", "list_patients", "success", request, str(current_doctor.id))
    return result


@router.get("/doctor/patients/{patient_id}/risk", response_model=RiskAssessmentResponse)
async def get_patient_risk(
    patient_id: str,
    request: Request,
    current_doctor: Doctor = Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    redis = _get_redis()
    cache_key = f"risk:{patient_id}"

    if redis:
        try:
            cached = redis.get(cache_key)
            if cached:
                data = json.loads(cached)
                write_structured_log(f"/v1/doctor/patients/{patient_id}/risk", "risk_cache_hit", "success", request, str(current_doctor.id), patient_id)
                return RiskAssessmentResponse(**data)
        except Exception as exc:
            logger.warning("Redis read error: %s", exc)

    try:
        patient = db.query(Patient).filter(Patient.id == patient_id).first()
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found")
        intake = db.query(PatientIntake).filter(PatientIntake.patient_id == patient.id).order_by(PatientIntake.submitted_at.desc()).first()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc

    dob = None
    if patient.dob_encrypted:
        try:
            dob = decrypt(patient.dob_encrypted)
        except ValueError:
            dob = None

    patient_data = {
        "name": patient.name,
        "dob": dob,
        "conditions": intake.conditions if intake else [],
        "medications": intake.medications if intake else [],
        "allergies": intake.allergies if intake else [],
        "symptoms": intake.symptoms if intake else "",
    }

    assessment_dict = await get_risk_assessment(patient_data)

    prev = db.query(RiskAssessment).filter(RiskAssessment.patient_id == patient_id).order_by(RiskAssessment.version.desc()).first()
    version = (prev.version + 1) if prev else 1

    try:
        assessment = RiskAssessment(
            patient_id=patient_id,
            version=version,
            risks=assessment_dict.get("risks", []),
            confidence=assessment_dict.get("confidence", "low"),
            summary=assessment_dict.get("summary", ""),
            source=assessment_dict.get("source", "rule_based"),
            doctor_id=current_doctor.id,
        )
        db.add(assessment)
        db.commit()
        db.refresh(assessment)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="Database unavailable") from exc

    response = RiskAssessmentResponse(
        id=assessment.id,
        risks=assessment.risks,
        confidence=assessment.confidence,
        summary=assessment.summary,
        source=assessment.source,
        version=assessment.version,
        created_at=assessment.created_at,
    )

    if redis:
        try:
            redis.setex(cache_key, 300, response.model_dump_json())
        except Exception as exc:
            logger.warning("Redis write error: %s", exc)

    _write_audit(db, f"/v1/doctor/patients/{patient_id}/risk", "risk_assessed", "success", str(current_doctor.id), patient_id, request.client.host if request.client else None)
    write_structured_log(f"/v1/doctor/patients/{patient_id}/risk", "risk_assessed", "success", request, str(current_doctor.id), patient_id)
    return response


@router.post("/doctor/patients/{patient_id}/feedback")
def submit_feedback(
    patient_id: str,
    body: FeedbackCreate,
    request: Request,
    current_doctor: Doctor = Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    try:
        fb = Feedback(
            patient_id=patient_id,
            doctor_id=body.doctor_id,
            action=body.action,
            reason=body.reason,
            assessment_id=body.assessment_id if body.assessment_id else None,
        )
        db.add(fb)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="Database unavailable") from exc

    # Invalidate risk cache so next view reflects updated feedback context
    redis = _get_redis()
    if redis:
        try:
            redis.delete(f"risk:{patient_id}")
        except Exception as exc:
            logger.warning("Redis cache invalidation failed: %s", exc)

        if body.action in ("override", "flag"):
            try:
                payload = json.dumps({
                    "patient_id": patient_id,
                    "doctor_id": body.doctor_id,
                    "action": body.action,
                    "reason": body.reason,
                    "assessment_id": body.assessment_id,
                    "timestamp": datetime.utcnow().isoformat(),
                })
                redis.lpush("retrain_queue", payload)
            except Exception as exc:
                logger.warning("Redis LPUSH failed: %s", exc)

    _write_audit(db, f"/v1/doctor/patients/{patient_id}/feedback", "feedback_submit", "success", str(current_doctor.id), patient_id, request.client.host if request.client else None)
    write_structured_log(f"/v1/doctor/patients/{patient_id}/feedback", "feedback_submit", "success", request, str(current_doctor.id), patient_id)
    return {"status": "recorded"}


@router.post("/doctor/retrain/trigger")
def trigger_retrain(x_internal_key: Annotated[str | None, Header()] = None):
    if x_internal_key != settings.INTERNAL_API_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")

    redis = _get_redis()
    if not redis:
        return {"processed": 0, "error": "Redis unavailable"}

    items = []
    while True:
        item = redis.rpop("retrain_queue")
        if item is None:
            break
        items.append(item)

    if items:
        RETRAIN_BUFFER.parent.mkdir(parents=True, exist_ok=True)
        with open(RETRAIN_BUFFER, "a") as f:
            for item in items:
                f.write(item + "\n")

    logger.info("retrain/trigger: wrote %d items to buffer", len(items))
    return {"processed": len(items)}


@router.get("/escalations/pending")
def pending_escalations(
    current_doctor: Doctor = Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    try:
        escalations = db.query(Escalation).filter(Escalation.acknowledged == False).all()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc

    result = []
    for esc in escalations:
        patient = db.query(Patient).filter(Patient.id == esc.patient_id).first()
        checkin = db.query(FollowupCheckin).filter(FollowupCheckin.id == esc.checkin_id).first()
        result.append({
            "id": str(esc.id),
            "patient_id": str(esc.patient_id),
            "patient_name": patient.name if patient else "Unknown",
            "urgency": checkin.urgency if checkin else "escalate",
            "reason": checkin.reason if checkin else "",
            "created_at": esc.created_at.isoformat(),
        })
    return result


app.include_router(router)
app.include_router(agent_router)


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
