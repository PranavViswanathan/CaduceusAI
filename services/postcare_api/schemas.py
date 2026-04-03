from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel


class CarePlanCreate(BaseModel):
    patient_id: str
    visit_notes: str


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
