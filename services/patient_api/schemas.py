from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, EmailStr, field_validator


class PatientRegister(BaseModel):
    email: str
    password: str
    name: str
    dob: str
    sex: str
    phone: str

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MedicationItem(BaseModel):
    name: str
    dose: str
    frequency: str


class IntakeCreate(BaseModel):
    conditions: list[str] = []
    medications: list[dict[str, Any]] = []
    allergies: list[str] = []
    symptoms: str


class IntakeResponse(BaseModel):
    id: UUID
    patient_id: UUID
    conditions: list[str]
    medications: list[dict[str, Any]]
    allergies: list[str]
    symptoms: str
    submitted_at: datetime

    class Config:
        from_attributes = True


class PatientResponse(BaseModel):
    id: UUID
    email: str
    name: str
    dob: str | None
    sex: str | None
    phone: str | None
    created_at: datetime
    intake: IntakeResponse | None = None

    class Config:
        from_attributes = True
