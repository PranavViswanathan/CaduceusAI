import logging
from datetime import datetime
from typing import Annotated

import redis as redis_lib
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from passlib.context import CryptContext
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy import text

from auth import create_access_token, get_current_patient, verify_token
from database import Base, SessionLocal, engine, get_db
from encryption import decrypt, encrypt
from logging_utils import write_structured_log
from models import AuditLog, Patient, PatientIntake
from schemas import IntakeCreate, IntakeResponse, PatientRegister, PatientResponse, Token
from settings import settings

logger = logging.getLogger(__name__)

app = FastAPI(title="Patient API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)


def _write_audit(
    db: Session,
    route: str,
    action: str,
    outcome: str,
    actor_id: str | None = None,
    patient_id: str | None = None,
    ip_address: str | None = None,
) -> None:
    try:
        entry = AuditLog(
            service="patient_api",
            route=route,
            actor_id=actor_id,
            patient_id=patient_id,
            action=action,
            outcome=outcome,
            ip_address=ip_address,
        )
        db.add(entry)
        db.commit()
    except Exception:
        db.rollback()


@app.post("/auth/register", status_code=status.HTTP_201_CREATED)
def register(body: PatientRegister, request: Request, db: Session = Depends(get_db)):
    existing = db.query(Patient).filter(Patient.email == body.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    try:
        patient = Patient(
            email=body.email,
            hashed_password=pwd_context.hash(body.password),
            name=body.name,
            dob_encrypted=encrypt(body.dob),
            sex=body.sex,
            phone=body.phone,
        )
        db.add(patient)
        db.commit()
        db.refresh(patient)
    except SQLAlchemyError as exc:
        db.rollback()
        logger.error("DB error on register: %s", exc)
        raise HTTPException(status_code=503, detail="Database unavailable") from exc

    _write_audit(db, "/auth/register", "register", "success", str(patient.id), str(patient.id), request.client.host if request.client else None)
    write_structured_log("/auth/register", "register", "success", request, str(patient.id))
    return {"message": "registered", "patient_id": str(patient.id)}


@app.post("/auth/token", response_model=Token)
def login(form: Annotated[OAuth2PasswordRequestForm, Depends()], request: Request, db: Session = Depends(get_db)):
    patient = db.query(Patient).filter(Patient.email == form.username).first()
    if not patient or not pwd_context.verify(form.password, patient.hashed_password):
        write_structured_log("/auth/token", "login", "failed", request)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token({"sub": str(patient.id)})
    _write_audit(db, "/auth/token", "login", "success", str(patient.id), str(patient.id), request.client.host if request.client else None)
    write_structured_log("/auth/token", "login", "success", request, str(patient.id))
    return Token(access_token=token)


@app.post("/patients/intake", response_model=IntakeResponse, status_code=status.HTTP_201_CREATED)
def submit_intake(
    body: IntakeCreate,
    request: Request,
    current_patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
):
    try:
        intake = PatientIntake(
            patient_id=current_patient.id,
            conditions=body.conditions,
            medications=body.medications,
            allergies=body.allergies,
            symptoms=body.symptoms,
        )
        db.add(intake)
        db.commit()
        db.refresh(intake)
    except SQLAlchemyError as exc:
        db.rollback()
        logger.error("DB error on intake: %s", exc)
        raise HTTPException(status_code=503, detail="Database unavailable") from exc

    _write_audit(db, "/patients/intake", "intake_submit", "success", str(current_patient.id), str(current_patient.id), request.client.host if request.client else None)
    write_structured_log("/patients/intake", "intake_submit", "success", request, str(current_patient.id))
    return IntakeResponse.model_validate(intake)


@app.get("/patients/{patient_id}", response_model=PatientResponse)
def get_patient(
    patient_id: str,
    request: Request,
    current_patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
):
    if str(current_patient.id) != patient_id:
        raise HTTPException(status_code=403, detail="Access denied")

    intake = (
        db.query(PatientIntake)
        .filter(PatientIntake.patient_id == current_patient.id)
        .order_by(PatientIntake.submitted_at.desc())
        .first()
    )

    dob_decrypted: str | None = None
    if current_patient.dob_encrypted:
        try:
            dob_decrypted = decrypt(current_patient.dob_encrypted)
        except ValueError:
            dob_decrypted = None

    _write_audit(db, f"/patients/{patient_id}", "patient_read", "success", str(current_patient.id), str(current_patient.id), request.client.host if request.client else None)
    write_structured_log(f"/patients/{patient_id}", "patient_read", "success", request, str(current_patient.id))

    return PatientResponse(
        id=current_patient.id,
        email=current_patient.email,
        name=current_patient.name,
        dob=dob_decrypted,
        sex=current_patient.sex,
        phone=current_patient.phone,
        created_at=current_patient.created_at,
        intake=IntakeResponse.model_validate(intake) if intake else None,
    )


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
