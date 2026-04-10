import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID

from database import Base


class AgentEscalation(Base):
    """Clinician-review queue entries created by the agent for urgent or
    low-confidence queries.  Kept separate from the postcare Escalation table
    (which requires a followup_checkin FK) so the agent layer stays decoupled
    from postcare workflows.
    """

    __tablename__ = "agent_escalations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), nullable=True)
    query_encrypted = Column(String, nullable=False)
    """PHI-encrypted original query text (Fernet/AES-256)."""
    query_type = Column(String, nullable=False, default="urgent")
    """Triage classification that caused escalation: 'urgent' or 'complex'."""
    reason = Column(Text, nullable=True)
    actor_id = Column(UUID(as_uuid=True), nullable=True)
    acknowledged = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
