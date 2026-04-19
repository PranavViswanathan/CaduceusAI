from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, EmailStr, field_validator


class DoctorRegister(BaseModel):
    email: EmailStr
    password: str
    name: str
    specialty: str = ""

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name cannot be empty")
        if len(v) > 200:
            raise ValueError("Name too long (max 200 characters)")
        return v

    @field_validator("specialty")
    @classmethod
    def specialty_length(cls, v: str) -> str:
        if len(v) > 200:
            raise ValueError("Specialty too long (max 200 characters)")
        return v


class LoginResponse(BaseModel):
    doctor_id: str
    token_type: str = "cookie"


# Kept for Swagger UI compatibility
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


class AssignmentResponse(BaseModel):
    id: UUID
    doctor_id: UUID
    patient_id: UUID
    assigned_at: datetime

    class Config:
        from_attributes = True


class FeedbackCreate(BaseModel):
    action: str
    reason: str | None = None
    assessment_id: str | None = None

    @field_validator("action")
    @classmethod
    def action_valid(cls, v: str) -> str:
        if v not in ("agree", "override", "flag"):
            raise ValueError("action must be agree, override, or flag")
        return v

    @field_validator("reason")
    @classmethod
    def reason_length(cls, v: str | None) -> str | None:
        if v is not None and len(v) > 2000:
            raise ValueError("Reason too long (max 2000 characters)")
        return v
