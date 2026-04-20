import json
import logging
import os
import re
import time
from datetime import datetime, timedelta

import httpx
from opentelemetry import metrics, trace

from settings import settings

_DEMO_MODE = os.getenv("DEMO_MODE", "").lower() == "true"

_DEMO_CARE_PLAN = {
    "follow_up_date": None,  # set at call time so relative dates stay fresh
    "medications_to_monitor": [
        "Lisinopril 10 mg — check BP weekly (demo)",
        "Metformin 500 mg — check fasting glucose at follow-up (demo)",
    ],
    "lifestyle_recommendations": [
        "Low-sodium diet (< 2 g/day) (demo)",
        "30 minutes moderate exercise 5 days/week (demo)",
        "Maintain regular sleep schedule 7–9 hours (demo)",
    ],
    "warning_signs": [
        "Chest pain or tightness (demo)",
        "Shortness of breath at rest (demo)",
        "Fever above 101°F (38.3°C) (demo)",
        "Sudden severe headache (demo)",
    ],
}

_DEMO_URGENCY_ROUTINE = {
    "urgency": "routine",
    "reason": "Demo mode: pre-scripted triage — no urgent keywords detected. Run 'make start' for real AI triage.",
}

logger = logging.getLogger(__name__)

tracer = trace.get_tracer(__name__)
_meter = metrics.get_meter(__name__)
_ollama_duration = _meter.create_histogram(
    "ollama.request.duration",
    unit="s",
    description="Duration of Ollama LLM inference calls",
)
_ollama_fallback = _meter.create_counter(
    "ollama.fallback",
    description="Times rule-based fallback was used instead of Ollama",
)

_STATIC_CARE_PLAN = {
    "follow_up_date": (datetime.utcnow() + timedelta(days=14)).date().isoformat(),
    "medications_to_monitor": ["Review all current medications at follow-up"],
    "lifestyle_recommendations": [
        "Maintain regular sleep schedule (7-9 hours)",
        "Stay well hydrated (8+ glasses of water daily)",
        "Follow prescribed dietary recommendations",
        "Avoid strenuous activity until cleared by physician",
    ],
    "warning_signs": [
        "Fever above 101°F (38.3°C)",
        "Severe or worsening chest pain",
        "Difficulty breathing or shortness of breath",
        "Sudden vision changes",
        "Severe headache or dizziness",
        "Signs of infection at any wound sites",
    ],
}


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


async def generate_care_plan(patient_id: str, visit_notes: str) -> dict:
    if _DEMO_MODE:
        plan = _DEMO_CARE_PLAN.copy()
        plan["follow_up_date"] = (datetime.utcnow() + timedelta(days=14)).date().isoformat()
        return plan

    follow_up = (datetime.utcnow() + timedelta(days=14)).date().isoformat()
    prompt = (
        "You are a clinical care coordinator. Based on the visit notes below, generate a structured "
        "care plan. Return ONLY valid JSON with these exact fields:\n"
        f'{{"follow_up_date": "{follow_up}", '
        '"medications_to_monitor": ["med1", "med2"], '
        '"lifestyle_recommendations": ["rec1", "rec2"], '
        '"warning_signs": ["sign1 the patient should call about", "sign2"]}}\n\n'
        f"Visit Notes:\n{visit_notes}"
    )
    attrs = {"ollama.operation": "care_plan"}

    with tracer.start_as_current_span("ollama.care_plan") as span:
        span.set_attribute("ollama.operation", "care_plan")
        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{settings.OLLAMA_URL}/api/generate",
                    json={"model": "llama3", "prompt": prompt, "stream": False},
                )
                resp.raise_for_status()
                raw = resp.json().get("response", "")
                parsed = _parse_json_response(raw)
                for field in ("follow_up_date", "medications_to_monitor", "lifestyle_recommendations", "warning_signs"):
                    if field not in parsed:
                        raise ValueError(f"Missing field: {field}")
                _ollama_duration.record(
                    time.perf_counter() - t0,
                    attributes={**attrs, "ollama.model": "llama3"},
                )
                span.set_attribute("ollama.model", "llama3")
                return parsed
        except Exception as exc:
            logger.warning("Ollama care plan generation failed: %s — using static template", exc)
            _ollama_fallback.add(1, attributes=attrs)
            span.set_attribute("ollama.fallback", True)
            return _STATIC_CARE_PLAN.copy()


def _rule_based_urgency(symptom_report: str) -> dict:
    report_lower = symptom_report.lower()
    escalate_keywords = ["chest pain", "can't breathe", "cannot breathe", "shortness of breath", "unconscious", "unresponsive", "severe pain", "heart attack", "stroke"]
    monitor_keywords = ["fever", "vomiting", "dizzy", "dizziness", "worsening", "swelling", "rash", "infection", "bleeding"]

    if any(kw in report_lower for kw in escalate_keywords):
        return {"urgency": "escalate", "reason": "Rule-based triage: critical symptom keyword detected (LLM unavailable)."}
    if any(kw in report_lower for kw in monitor_keywords):
        return {"urgency": "monitor", "reason": "Rule-based triage: concerning symptom keyword detected (LLM unavailable)."}
    return {"urgency": "routine", "reason": "Rule-based triage: no urgent keyword detected (LLM unavailable)."}


async def assess_checkin_urgency(symptom_report: str, care_plan: dict) -> dict:
    if _DEMO_MODE:
        report_lower = symptom_report.lower()
        escalate_keywords = ["chest pain", "can't breathe", "shortness of breath", "unconscious", "stroke"]
        if any(kw in report_lower for kw in escalate_keywords):
            return {
                "urgency": "escalate",
                "reason": "Demo mode: critical keyword detected — escalated to clinician. Run 'make start' for real AI triage.",
            }
        return _DEMO_URGENCY_ROUTINE.copy()

    warning_signs = care_plan.get("warning_signs", [])
    prompt = (
        "You are a triage nurse. Given the patient's care plan warning signs and their symptom report, "
        "assess the urgency. Urgency must be one of: routine, monitor, or escalate.\n"
        "Return ONLY valid JSON: {\"urgency\": \"routine|monitor|escalate\", \"reason\": \"brief explanation\"}\n\n"
        f"Care Plan Warning Signs:\n{chr(10).join(f'- {s}' for s in warning_signs)}\n\n"
        f"Patient Symptom Report:\n{symptom_report}"
    )
    attrs = {"ollama.operation": "urgency_assessment"}

    with tracer.start_as_current_span("ollama.urgency_assessment") as span:
        span.set_attribute("ollama.operation", "urgency_assessment")
        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{settings.OLLAMA_URL}/api/generate",
                    json={"model": "llama3", "prompt": prompt, "stream": False},
                )
                resp.raise_for_status()
                raw = resp.json().get("response", "")
                parsed = _parse_json_response(raw)
                if parsed.get("urgency") not in ("routine", "monitor", "escalate"):
                    raise ValueError("Invalid urgency value")
                _ollama_duration.record(
                    time.perf_counter() - t0,
                    attributes={**attrs, "ollama.model": "llama3"},
                )
                span.set_attribute("ollama.model", "llama3")
                return parsed
        except Exception as exc:
            logger.warning("Ollama urgency assessment failed: %s — using rule-based fallback", exc)
            _ollama_fallback.add(1, attributes=attrs)
            span.set_attribute("ollama.fallback", True)
            return _rule_based_urgency(symptom_report)
