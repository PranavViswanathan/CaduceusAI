import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Column, Date, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID

from database import Base


class Patient(Base):
    __tablename__ = "patients"

    id = Column(UUID(as_uuid=True), primary_key=True)
    email = Column(String)
    name = Column(String)
    created_at = Column(DateTime)


class CarePlan(Base):
    __tablename__ = "care_plans"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False)
    follow_up_date = Column(Date, nullable=True)
    medications_to_monitor = Column(JSON, default=list)
    lifestyle_recommendations = Column(JSON, default=list)
    warning_signs = Column(JSON, default=list)
    visit_notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class FollowupCheckin(Base):
    __tablename__ = "followup_checkins"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False)
    symptom_report = Column(Text)
    urgency = Column(String)
    reason = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class Escalation(Base):
    __tablename__ = "escalations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    checkin_id = Column(UUID(as_uuid=True), ForeignKey("followup_checkins.id"), nullable=False)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False)
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
