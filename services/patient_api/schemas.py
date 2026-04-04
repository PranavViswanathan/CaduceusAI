import re
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, EmailStr, field_validator


class PatientRegister(BaseModel):
    email: EmailStr
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

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name cannot be empty")
        if len(v) > 200:
            raise ValueError("Name too long (max 200 characters)")
        return v

    @field_validator("dob")
    @classmethod
    def dob_format(cls, v: str) -> str:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            raise ValueError("Date of birth must be in YYYY-MM-DD format")
        return v

    @field_validator("phone")
    @classmethod
    def phone_length(cls, v: str) -> str:
        if len(v) > 20:
            raise ValueError("Phone number too long (max 20 characters)")
        return v

    @field_validator("sex")
    @classmethod
    def sex_valid(cls, v: str) -> str:
        valid_values = {"male", "female", "other", "prefer_not_to_say"}
        if v.lower() not in valid_values:
            raise ValueError(f"Sex must be one of: {', '.join(sorted(valid_values))}")
        return v.lower()


class LoginResponse(BaseModel):
    patient_id: str
    token_type: str = "cookie"


# Kept for Swagger UI compatibility
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MedicationItem(BaseModel):
    name: str
    dose: str
    frequency: str

    @field_validator("name", "dose", "frequency")
    @classmethod
    def field_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Field cannot be empty")
        if len(v) > 200:
            raise ValueError("Field too long (max 200 characters)")
        return v


class IntakeCreate(BaseModel):
    conditions: list[str] = []
    medications: list[dict[str, Any]] = []
    allergies: list[str] = []
    symptoms: str

    @field_validator("symptoms")
    @classmethod
    def symptoms_length(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 10:
            raise ValueError("Symptoms must be at least 10 characters")
        if len(v) > 5000:
            raise ValueError("Symptoms too long (max 5000 characters)")
        return v

    @field_validator("conditions", "allergies")
    @classmethod
    def list_items_length(cls, items: list[str]) -> list[str]:
        for item in items:
            if len(item.strip()) > 200:
                raise ValueError("Item too long (max 200 characters)")
        return items


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
