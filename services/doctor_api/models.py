import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID

from database import Base


class Patient(Base):
    __tablename__ = "patients"

    id = Column(UUID(as_uuid=True), primary_key=True)
    email = Column(String)
    name = Column(String)
    dob_encrypted = Column(String)
    sex = Column(String)
    phone = Column(String)
    created_at = Column(DateTime)


class PatientIntake(Base):
    __tablename__ = "patient_intake"

    id = Column(UUID(as_uuid=True), primary_key=True)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id"))
    conditions = Column(JSON)
    medications = Column(JSON)
    allergies = Column(JSON)
    symptoms = Column(Text)
    submitted_at = Column(DateTime)


class Doctor(Base):
    __tablename__ = "doctors"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    name = Column(String, nullable=False)
    specialty = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)


class RiskAssessment(Base):
    __tablename__ = "risk_assessments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False)
    version = Column(Integer, default=1)
    risks = Column(JSON)
    confidence = Column(String)
    summary = Column(Text)
    source = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    doctor_id = Column(UUID(as_uuid=True), nullable=True)


class Feedback(Base):
    __tablename__ = "feedback"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False)
    doctor_id = Column(UUID(as_uuid=True), ForeignKey("doctors.id"), nullable=False)
    action = Column(String)
    reason = Column(Text, nullable=True)
    assessment_id = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class FollowupCheckin(Base):
    __tablename__ = "followup_checkins"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id"))
    symptom_report = Column(Text)
    urgency = Column(String)
    reason = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class Escalation(Base):
    __tablename__ = "escalations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    checkin_id = Column(UUID(as_uuid=True), ForeignKey("followup_checkins.id"))
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id"))
    acknowledged = Column(Boolean, default=False)
    acknowledged_by = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    service = Column(String)
    route = Column(String)
    actor_id = Column(UUID(as_uuid=True), nullable=True)
    patient_id = Column(UUID(as_uuid=True), nullable=True)
    action = Column(String)
    outcome = Column(String)
    ip_address = Column(String, nullable=True)
