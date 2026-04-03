from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class DoctorRegister(BaseModel):
    email: str
    password: str
    name: str
    specialty: str = ""


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class PatientListItem(BaseModel):
    id: UUID
    name: str
    email: str
    intake_submitted_at: datetime | None = None

    class Config:
        from_attributes = True


class PatientDetail(BaseModel):
    id: UUID
    name: str
    email: str
    dob: str | None
    sex: str | None
    phone: str | None
    conditions: list[str]
    medications: list[dict[str, Any]]
    allergies: list[str]
    symptoms: str | None


class RiskAssessmentResponse(BaseModel):
    id: UUID
    risks: list[str]
    confidence: str
    summary: str
    source: str
    version: int
    created_at: datetime

    class Config:
        from_attributes = True


class FeedbackCreate(BaseModel):
    action: str
    reason: str | None = None
    doctor_id: str
    assessment_id: str | None = None
