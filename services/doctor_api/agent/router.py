"""FastAPI router for the CaduceusAI agent endpoints.

Registers two routes under the /v1/agent prefix:
  POST /v1/agent/query   — run the LangGraph agent on a clinical query
  GET  /v1/agent/graph   — return the graph definition JSON for visualisation

Import this module in doctor_api/main.py:

    from agent.router import agent_router
    app.include_router(agent_router)

Importing this module also registers the AgentEscalation model with SQLAlchemy's
Base so that Base.metadata.create_all() in the startup hook creates the
agent_escalations table automatically.
"""

import hashlib
import json
import logging
from typing import Optional

import redis as redis_lib
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import get_current_doctor
from database import get_db
from models import Doctor
from settings import settings

from .graph import get_graph_definition, graph
from .models import AgentEscalation  # noqa: F401 — registers table with Base

logger = logging.getLogger(__name__)

agent_router = APIRouter(prefix="/v1/agent", tags=["agent"])


# ── Pydantic schemas ──────────────────────────────────────────────────────────


class AgentQueryRequest(BaseModel):
    query: str
    """The clinical question or instruction to send to the agent."""

    patient_id: Optional[str] = None
    """Optional patient UUID to attach to audit and escalation records."""

    feedback_score: Optional[float] = None
    """Clinician feedback score (0.0–1.0) for a prior agent response.
    If provided and below the configured threshold, a retraining job is
    enqueued to the Redis retrain_queue."""

    feedback_assessment_id: Optional[str] = None
    """Assessment UUID associated with feedback_score, forwarded to the
    retrain queue payload for traceability."""


class AgentQueryResponse(BaseModel):
    query_type: str
    """Triage classification: 'routine' | 'complex' | 'urgent'."""

    response: str
    """The agent's final answer, or a 'pending review' message if escalated."""

    confidence: float
    """Model confidence in the response (0.0–1.0)."""

    requires_escalation: bool
    """True when the query was escalated to the clinician review queue."""

    escalation_id: Optional[str] = None
    """UUID of the created AgentEscalation record, when requires_escalation is True."""

    chain_of_thought: Optional[str] = None
    """Step-by-step reasoning trace produced by reasoning_node, if applicable."""


# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_redis():
    """Return a connected Redis client, or None if Redis is unavailable.

    Mirrors the _get_redis() helper in main.py so the agent reuses the same
    Redis URL configuration without opening a new persistent connection.
    """
    try:
        r = redis_lib.from_url(
            settings.REDIS_URL, decode_responses=True, socket_connect_timeout=2
        )
        r.ping()
        return r
    except Exception:
        return None


# ── Routes ────────────────────────────────────────────────────────────────────


@agent_router.post("/query", response_model=AgentQueryResponse)
async def agent_query(
    body: AgentQueryRequest,
    request: Request,
    current_doctor: Doctor = Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    """Run the LangGraph agent on a clinical query.

    The agent is a five-node StateGraph that:
      1. Triages the query (routine / complex / urgent)
      2. Answers routine queries via RAG
      3. Reasons through complex queries with chain-of-thought
      4. Escalates urgent or low-confidence queries to the clinician queue
      5. Optionally triggers model retraining based on feedback score

    All terminal paths write an audit log entry to the audit_log table.
    Urgent queries and their raw text are stored PHI-encrypted.
    """
    redis = _get_redis()

    cache_key = "agent:" + hashlib.sha256(
        f"{body.query.lower().strip()}|{body.patient_id or ''}".encode()
    ).hexdigest()[:16]

    if redis:
        try:
            cached = redis.get(cache_key)
            if cached:
                logger.info("agent_query: cache hit for key %s", cache_key)
                return AgentQueryResponse(**json.loads(cached))
        except Exception as exc:
            logger.warning("agent_query: Redis read error: %s", exc)

    initial_state = {
        "query": body.query,
        "patient_id": body.patient_id,
        "actor_id": str(current_doctor.id),
        "ip_address": request.client.host if request.client else None,
        "query_type": "",
        "rag_context": [],
        "chain_of_thought": "",
        "response": "",
        "confidence": 0.0,
        "feedback_score": body.feedback_score,
        "feedback_assessment_id": body.feedback_assessment_id,
        "requires_escalation": False,
        "escalation_id": None,
    }

    try:
        result = await graph.ainvoke(
            initial_state,
            config={"configurable": {"db": db, "redis": redis}},
        )
    except Exception as exc:
        logger.error("agent_query: graph execution failed: %s", exc)
        raise HTTPException(status_code=503, detail="Agent temporarily unavailable") from exc

    agent_response = AgentQueryResponse(
        query_type=result["query_type"],
        response=result["response"],
        confidence=result["confidence"],
        requires_escalation=result["requires_escalation"],
        escalation_id=result.get("escalation_id"),
        chain_of_thought=result.get("chain_of_thought") or None,
    )

    if redis and not agent_response.requires_escalation:
        try:
            redis.setex(cache_key, 300, agent_response.model_dump_json())
        except Exception as exc:
            logger.warning("agent_query: Redis write error: %s", exc)

    return agent_response


@agent_router.get("/graph")
def agent_graph_definition(
    current_doctor: Doctor = Depends(get_current_doctor),
):
    """Return the LangGraph graph definition as JSON.

    Useful for developer tooling and integration with LangGraph Studio.
    The same graph object is also exposed via the module-level `graph`
    variable in agent/graph.py for direct Studio consumption.
    """
    return get_graph_definition()
