import json
import sys
from datetime import datetime

from fastapi import Request


def write_structured_log(
    route: str,
    action: str,
    outcome: str,
    request: Request | None = None,
    actor_id: str | None = None,
    patient_id: str | None = None,
) -> None:
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "service": "postcare_api",
        "route": route,
        "actor_id": actor_id,
        "patient_id": patient_id,
        "action": action,
        "outcome": outcome,
        "ip": request.client.host if request and request.client else None,
    }
    print(json.dumps(entry), file=sys.stdout, flush=True)
