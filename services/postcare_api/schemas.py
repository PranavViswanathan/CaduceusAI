from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, field_validator


class CarePlanCreate(BaseModel):
    patient_id: str
    visit_notes: str

    @field_validator("visit_notes")
    @classmethod
    def visit_notes_length(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Visit notes cannot be empty")
        if len(v) > 10000:
            raise ValueError("Visit notes too long (max 10000 characters)")
        return v

    @field_validator("patient_id")
    @classmethod
    def patient_id_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("patient_id cannot be empty")
        return v


class CarePlanResponse(BaseModel):
    id: UUID
    patient_id: UUID
    follow_up_date: date | None
    medications_to_monitor: list[str]
    lifestyle_recommendations: list[str]
    warning_signs: list[str]
    visit_notes: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class CheckinCreate(BaseModel):
    patient_id: str
    symptom_report: str

    @field_validator("symptom_report")
    @classmethod
    def symptom_report_length(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 10:
            raise ValueError("Symptom report must be at least 10 characters")
        if len(v) > 5000:
            raise ValueError("Symptom report too long (max 5000 characters)")
        return v

    @field_validator("patient_id")
    @classmethod
    def patient_id_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("patient_id cannot be empty")
        return v


class CheckinResponse(BaseModel):
    id: UUID
    patient_id: UUID
    urgency: str
    reason: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class EscalationResponse(BaseModel):
    id: UUID
    patient_id: UUID
    checkin_id: UUID
    acknowledged: bool
    created_at: datetime

    class Config:
        from_attributes = True
