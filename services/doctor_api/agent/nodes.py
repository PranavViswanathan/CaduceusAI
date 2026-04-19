"""LangGraph node functions for the CaduceusAI agent graph.

Each node is an async function that accepts (state, config) and returns a dict
of the state keys it modifies.  LangGraph merges the returned dict into the
running state, leaving all other keys unchanged.

Dependencies (db session, redis client) are injected via RunnableConfig so that
nodes remain pure functions of state and the existing FastAPI connection objects
are reused — no new connections are opened here.
"""

import json
import logging
import os
import re
import time
from datetime import datetime
from typing import Optional

import httpx
from langchain_core.runnables import RunnableConfig
from opentelemetry import metrics, trace
from sqlalchemy.orm import Session

from encryption import encrypt
from models import AuditLog
from settings import settings

from .knowledge_base import retrieve
from .models import AgentEscalation
from .state import AgentState

logger = logging.getLogger(__name__)

tracer = trace.get_tracer(__name__)
_meter = metrics.get_meter(__name__)
_node_duration = _meter.create_histogram(
    "agent.node.duration",
    unit="s",
    description="Duration of LangGraph agent node execution",
)

_RETRAIN_SCORE_THRESHOLD: float = float(
    os.getenv("RETRAIN_SCORE_THRESHOLD", "0.4")
)


# ── Internal helpers ──────────────────────────────────────────────────────────


def _parse_json_response(raw: str) -> dict:
    raw = raw.strip()
    match = re.search(r"\{.*?\}", raw, re.DOTALL)
    if not match:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
    candidate = match.group() if match else raw
    candidate = re.sub(
        r"[\x00-\x1f\x7f]",
        lambda m: " " if m.group() in "\t\n\r" else "",
        candidate,
    )
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        logger.warning("_parse_json_response: failed to parse JSON (%s)", exc)
        return {}


def _write_audit(
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


# ── Node 1: triage_node ───────────────────────────────────────────────────────


async def triage_node(state: AgentState, config: RunnableConfig) -> dict:
    query = state["query"]
    prompt = (
        "You are a medical query triage system. Classify the query below into exactly one of: "
        "routine, complex, urgent.\n\n"
        "Definitions:\n"
        "  routine   — general information request, medication question, low-acuity symptom check, "
        "administrative question\n"
        "  complex   — multi-factor clinical reasoning, differential diagnosis, treatment planning, "
        "interpreting lab results, drug-drug interaction analysis\n"
        "  urgent    — life-threatening symptoms (chest pain, shortness of breath, stroke signs, "
        "severe allergic reaction), suicidal ideation, or any situation requiring immediate "
        "clinical attention\n\n"
        f"Query: {query}\n\n"
        'Reply with ONLY valid JSON: {"classification": "routine"} '
        'or {"classification": "complex"} or {"classification": "urgent"}'
    )

    query_type = "complex"
    t0 = time.perf_counter()

    with tracer.start_as_current_span("agent.triage") as span:
        span.set_attribute("agent.node", "triage")
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{settings.OLLAMA_URL}/api/generate",
                    json={"model": "llama3", "prompt": prompt, "stream": False},
                )
                resp.raise_for_status()
                raw = resp.json().get("response", "")
                parsed = _parse_json_response(raw)
                label = parsed.get("classification", "").lower()
                if label in ("routine", "complex", "urgent"):
                    query_type = label
                else:
                    logger.warning(
                        "triage_node: unexpected classification %r — defaulting to 'complex'", label
                    )
        except httpx.ConnectError:
            logger.warning("triage_node: Ollama unreachable — defaulting to 'complex'")
        except Exception as exc:
            logger.warning("triage_node: inference failed (%s) — defaulting to 'complex'", exc)

        span.set_attribute("agent.query_type", query_type)
        _node_duration.record(
            time.perf_counter() - t0,
            attributes={"agent.node": "triage"},
        )

    return {"query_type": query_type}


# ── Node 2: rag_node ──────────────────────────────────────────────────────────


async def rag_node(state: AgentState, config: RunnableConfig) -> dict:
    query = state["query"]
    docs = retrieve(query)
    context = "\n\n---\n\n".join(docs) if docs else "No relevant documents found."

    prompt = (
        "You are a clinical decision-support assistant. Answer the question using ONLY the "
        "provided context. If the context does not contain enough information to answer "
        "confidently, say so explicitly — do not invent clinical facts.\n\n"
        "Reply with ONLY a JSON object in this exact format:\n"
        '{"response": "your answer here", "confidence": 0.85}\n'
        "confidence is a float between 0.0 (completely uncertain) and 1.0 (fully certain).\n\n"
        f"Context:\n{context}\n\n"
        f"Question: {query}\n\n"
        "JSON:"
    )

    response_text = (
        "I was unable to retrieve sufficient information to answer your query. "
        "Please consult current clinical guidelines or a specialist."
    )
    confidence = 0.2
    t0 = time.perf_counter()

    with tracer.start_as_current_span("agent.rag") as span:
        span.set_attribute("agent.node", "rag")
        span.set_attribute("agent.docs_retrieved", len(docs))
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{settings.OLLAMA_URL}/api/generate",
                    json={"model": "llama3", "prompt": prompt, "stream": False},
                )
                resp.raise_for_status()
                raw = resp.json().get("response", "")
                parsed = _parse_json_response(raw)
                response_text = parsed.get("response", response_text)
                confidence = max(0.0, min(1.0, float(parsed.get("confidence", 0.2))))
        except httpx.ConnectError:
            logger.warning("rag_node: Ollama unreachable — returning fallback response")
        except Exception as exc:
            logger.warning("rag_node: inference failed (%s) — returning fallback response", exc)

        span.set_attribute("agent.confidence", confidence)
        _node_duration.record(
            time.perf_counter() - t0,
            attributes={"agent.node": "rag"},
        )

    return {
        "rag_context": docs,
        "response": response_text,
        "confidence": confidence,
    }


# ── Node 3: reasoning_node ────────────────────────────────────────────────────


async def reasoning_node(state: AgentState, config: RunnableConfig) -> dict:
    query = state["query"]
    prompt = (
        "You are a clinical reasoning assistant. Think through the query step-by-step "
        "before producing a final answer.\n\n"
        "Reply with ONLY a JSON object in this exact format:\n"
        "{\n"
        '  "chain_of_thought": "Step 1: ... Step 2: ... Conclusion: ...",\n'
        '  "response": "Final answer in plain clinical language.",\n'
        '  "confidence": 0.75\n'
        "}\n"
        "confidence is a float between 0.0 and 1.0 representing your certainty.\n"
        "Set confidence < 0.5 if the query involves potential emergency, you are unsure, "
        "or the answer requires specialist judgement beyond your reasoning.\n\n"
        f"Query: {query}\n\n"
        "JSON:"
    )

    response_text = (
        "This query requires specialist clinical review. "
        "Please consult the relevant department."
    )
    chain_of_thought = ""
    confidence = 0.3
    t0 = time.perf_counter()

    with tracer.start_as_current_span("agent.reasoning") as span:
        span.set_attribute("agent.node", "reasoning")
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{settings.OLLAMA_URL}/api/generate",
                    json={"model": "llama3", "prompt": prompt, "stream": False},
                )
                resp.raise_for_status()
                raw = resp.json().get("response", "")
                parsed = _parse_json_response(raw)
                response_text = parsed.get("response", response_text)
                chain_of_thought = parsed.get("chain_of_thought", "")
                confidence = max(0.0, min(1.0, float(parsed.get("confidence", 0.3))))
        except httpx.ConnectError:
            logger.warning("reasoning_node: Ollama unreachable — defaulting to low confidence")
        except Exception as exc:
            logger.warning(
                "reasoning_node: inference failed (%s) — defaulting to low confidence", exc
            )

        span.set_attribute("agent.confidence", confidence)
        _node_duration.record(
            time.perf_counter() - t0,
            attributes={"agent.node": "reasoning"},
        )

    return {
        "response": response_text,
        "chain_of_thought": chain_of_thought,
        "confidence": confidence,
    }


# ── Node 4: escalation_node ───────────────────────────────────────────────────


async def escalation_node(state: AgentState, config: RunnableConfig) -> dict:
    db: Session = config["configurable"]["db"]
    query = state["query"]
    actor_id = state.get("actor_id")
    patient_id = state.get("patient_id")
    ip_address = state.get("ip_address")
    query_type = state.get("query_type", "urgent")

    escalation_id: Optional[str] = None
    outcome = "db_error"
    t0 = time.perf_counter()

    with tracer.start_as_current_span("agent.escalation") as span:
        span.set_attribute("agent.node", "escalation")
        span.set_attribute("agent.query_type", query_type)
        try:
            escalation = AgentEscalation(
                patient_id=patient_id,
                query_encrypted=encrypt(query),
                query_type=query_type,
                reason=f"Agent-triaged as '{query_type}'; routed to clinician review.",
                actor_id=actor_id,
            )
            db.add(escalation)
            db.commit()
            db.refresh(escalation)
            escalation_id = str(escalation.id)
            outcome = "escalated"
        except Exception as exc:
            logger.error("escalation_node: failed to write AgentEscalation (%s)", exc)
            try:
                db.rollback()
            except Exception:
                pass

        span.set_attribute("agent.outcome", outcome)
        _node_duration.record(
            time.perf_counter() - t0,
            attributes={"agent.node": "escalation"},
        )

    _write_audit(
        db,
        route="/v1/agent/query",
        action="agent_escalation",
        outcome=outcome,
        actor_id=actor_id,
        patient_id=patient_id,
        ip=ip_address,
    )

    return {
        "response": (
            "This query has been flagged for clinician review. "
            "A member of the clinical team will respond as soon as possible."
        ),
        "requires_escalation": True,
        "escalation_id": escalation_id,
        "confidence": 0.0,
    }


# ── Node 5: retraining_trigger_node ──────────────────────────────────────────


async def retraining_trigger_node(state: AgentState, config: RunnableConfig) -> dict:
    db: Session = config["configurable"]["db"]
    redis = config["configurable"].get("redis")
    actor_id = state.get("actor_id")
    patient_id = state.get("patient_id")
    ip_address = state.get("ip_address")
    feedback_score = state.get("feedback_score")
    feedback_assessment_id = state.get("feedback_assessment_id")

    retrain_enqueued = False
    t0 = time.perf_counter()

    with tracer.start_as_current_span("agent.retraining_trigger") as span:
        span.set_attribute("agent.node", "retraining_trigger")
        if (
            redis is not None
            and feedback_score is not None
            and feedback_score < _RETRAIN_SCORE_THRESHOLD
        ):
            try:
                payload = json.dumps({
                    "patient_id": patient_id,
                    "assessment_id": feedback_assessment_id,
                    "feedback_score": feedback_score,
                    "action": "agent_low_score",
                    "timestamp": datetime.utcnow().isoformat(),
                })
                redis.lpush("retrain_queue", payload)
                retrain_enqueued = True
                logger.info(
                    "retraining_trigger_node: enqueued retrain job "
                    "(score=%.2f threshold=%.2f assessment=%s)",
                    feedback_score,
                    _RETRAIN_SCORE_THRESHOLD,
                    feedback_assessment_id,
                )
            except Exception as exc:
                logger.warning("retraining_trigger_node: Redis lpush failed (%s)", exc)

        span.set_attribute("agent.retrain_enqueued", retrain_enqueued)
        _node_duration.record(
            time.perf_counter() - t0,
            attributes={"agent.node": "retraining_trigger"},
        )

    _write_audit(
        db,
        route="/v1/agent/query",
        action="agent_query_complete",
        outcome="retrain_enqueued" if retrain_enqueued else state.get("query_type", ""),
        actor_id=actor_id,
        patient_id=patient_id,
        ip=ip_address,
    )

    return {}
