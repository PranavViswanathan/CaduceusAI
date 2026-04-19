import json
import logging
import re
import time

import httpx
import redis as redis_lib
from opentelemetry import metrics, trace

from settings import settings

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

_DANGEROUS_COMBOS = [
    {
        "a": ["warfarin"],
        "b": ["ibuprofen", "naproxen", "aspirin", "nsaid", "celecoxib", "diclofenac"],
        "message": "Warfarin combined with NSAIDs significantly raises bleeding risk.",
    },
    {
        "a": ["sertraline", "fluoxetine", "paroxetine", "escitalopram", "citalopram"],
        "b": ["phenelzine", "tranylcypromine", "selegiline", "isocarboxazid"],
        "message": "SSRI + MAOI combination can cause life-threatening serotonin syndrome.",
    },
    {
        "a": ["metformin"],
        "b": ["contrast", "iodine contrast", "contrast dye", "iohexol", "iopamidol"],
        "message": "Metformin should be held before iodine contrast procedures due to lactic acidosis risk.",
    },
]


def _extract_medication_names(medications: list) -> list[str]:
    names = []
    for med in medications:
        if isinstance(med, dict):
            name = med.get("name", "")
        else:
            name = str(med)
        names.append(name.lower().strip())
    return names


def rule_based_assessment(patient_data: dict) -> dict:
    med_names = _extract_medication_names(patient_data.get("medications", []))
    risks = []

    for combo in _DANGEROUS_COMBOS:
        has_a = any(drug in " ".join(med_names) for drug in combo["a"])
        has_b = any(drug in " ".join(med_names) for drug in combo["b"])
        if has_a and has_b:
            risks.append(combo["message"])

    if not risks:
        return {
            "risks": ["No known high-risk drug interactions detected."],
            "confidence": "low",
            "summary": "No critical interactions found by rule engine.",
            "source": "rule_based",
        }

    return {
        "risks": risks,
        "confidence": "low",
        "summary": f"Rule-based engine identified {len(risks)} potential risk(s). LLM analysis unavailable.",
        "source": "rule_based",
    }


def _build_prompt(patient_data: dict) -> str:
    conditions = ", ".join(patient_data.get("conditions", [])) or "None"
    medications = "; ".join(
        m.get("name", str(m)) if isinstance(m, dict) else str(m)
        for m in patient_data.get("medications", [])
    ) or "None"
    allergies = ", ".join(patient_data.get("allergies", [])) or "None"
    symptoms = patient_data.get("symptoms") or "None"

    return (
        "You are a clinical risk assessment tool. Reply with ONLY a JSON object — no prose, no markdown.\n"
        "Required format: "
        '{"risks":["short risk 1","short risk 2"],"confidence":"low","summary":"one sentence"}\n'
        "confidence must be exactly: low, medium, or high.\n\n"
        f"Conditions: {conditions}\n"
        f"Medications: {medications}\n"
        f"Allergies: {allergies}\n"
        f"Symptoms: {symptoms}\n\n"
        "JSON:"
    )


def _parse_llm_json(raw: str) -> dict:
    raw = raw.strip()
    json_match = re.search(r"\{.*?\}", raw, re.DOTALL)
    if not json_match:
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
    candidate = json_match.group() if json_match else raw
    candidate = re.sub(r"[\x00-\x1f\x7f]", lambda m: " " if m.group() in "\t\n\r" else "", candidate)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        logger.warning("_parse_llm_json: failed to parse JSON (%s)", exc)
        return {}


def _available_ollama_models() -> set[str]:
    try:
        resp = httpx.get(f"{settings.OLLAMA_URL}/api/tags", timeout=5.0)
        resp.raise_for_status()
        return {m.get("name", "").split(":")[0] for m in resp.json().get("models", [])}
    except Exception:
        return set()


def _get_active_model() -> str:
    try:
        r = redis_lib.from_url(settings.REDIS_URL, decode_responses=True, socket_connect_timeout=2)
        r.ping()
        active = r.get("active_model")
        if active:
            return active
    except Exception:
        pass
    return settings.OLLAMA_MODEL


def _model_priority_list() -> list[str]:
    available = _available_ollama_models()
    active = _get_active_model()
    ft_name = settings.FINE_TUNED_MODEL_NAME
    candidates = [active, ft_name, "llama3", "mistral"]

    seen: set[str] = set()
    unique: list[str] = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            unique.append(c)

    def is_available(model: str) -> bool:
        return model.split(":")[0] in available

    return [m for m in unique if is_available(m)] or [active, "llama3", "mistral"]


async def get_risk_assessment(patient_data: dict) -> dict:
    prompt = _build_prompt(patient_data)
    models = _model_priority_list()
    attrs = {"ollama.operation": "risk_assessment"}

    with tracer.start_as_current_span("ollama.risk_assessment") as span:
        span.set_attribute("ollama.operation", "risk_assessment")
        span.set_attribute("ollama.model_count", len(models))

        for model in models:
            t0 = time.perf_counter()
            try:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    resp = await client.post(
                        f"{settings.OLLAMA_URL}/api/generate",
                        json={"model": model, "prompt": prompt, "stream": False},
                    )
                    resp.raise_for_status()
                    raw_text = resp.json().get("response", "")
                    parsed = _parse_llm_json(raw_text)
                    if "risks" not in parsed or "confidence" not in parsed or "summary" not in parsed:
                        raise ValueError("Missing required fields in LLM response")
                    _ollama_duration.record(
                        time.perf_counter() - t0,
                        attributes={**attrs, "ollama.model": model},
                    )
                    parsed["source"] = f"llm:{model}"
                    span.set_attribute("ollama.model", model)
                    return parsed
            except httpx.ConnectError:
                logger.warning("Ollama not reachable, skipping model %s", model)
                break
            except (httpx.TimeoutException, httpx.HTTPStatusError) as exc:
                logger.warning("Ollama request failed (model=%s): %s", model, exc)
                continue
            except (json.JSONDecodeError, ValueError, KeyError) as exc:
                logger.warning("LLM response parse error (model=%s): %s", model, exc)
                continue

        _ollama_fallback.add(1, attributes=attrs)
        span.set_attribute("ollama.fallback", True)
        return rule_based_assessment(patient_data)
