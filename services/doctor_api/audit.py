import logging
from typing import Optional

from sqlalchemy.orm import Session

from models import AuditLog

logger = logging.getLogger(__name__)


def write_audit(
    db: Session,
    route: str,
    action: str,
    outcome: str,
    actor_id: Optional[str] = None,
    patient_id: Optional[str] = None,
    ip: Optional[str] = None,
) -> None:
    try:
        entry = AuditLog(
            service="doctor_api",
            route=route,
            actor_id=actor_id,
            patient_id=patient_id,
            action=action,
            outcome=outcome,
            ip_address=ip,
        )
        db.add(entry)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("CRITICAL: audit log write failed (route=%s action=%s): %s", route, action, exc)
