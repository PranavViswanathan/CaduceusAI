import json
import logging
import re

import httpx

from settings import settings

logger = logging.getLogger(__name__)

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
    # Extract the first {...} block
    json_match = re.search(r"\{.*?\}", raw, re.DOTALL)
    if not json_match:
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
    candidate = json_match.group() if json_match else raw
    # Remove control characters that break JSON parsing
    candidate = re.sub(r"[\x00-\x1f\x7f]", lambda m: " " if m.group() in "\t\n\r" else "", candidate)
    return json.loads(candidate)


async def get_risk_assessment(patient_data: dict) -> dict:
    prompt = _build_prompt(patient_data)

    for model in ("llama3", "mistral"):
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{settings.OLLAMA_URL}/api/generate",
                    json={"model": model, "prompt": prompt, "stream": False},
                )
                resp.raise_for_status()
                raw_text = resp.json().get("response", "")
                parsed = _parse_llm_json(raw_text)
                parsed["source"] = "llm"
                if "risks" not in parsed or "confidence" not in parsed or "summary" not in parsed:
                    raise ValueError("Missing required fields in LLM response")
                return parsed
        except httpx.ConnectError:
            logger.warning("Ollama not reachable with model %s, trying fallback", model)
            break
        except (httpx.TimeoutException, httpx.HTTPStatusError) as exc:
            logger.warning("Ollama request failed (%s): %s — using rule-based fallback", model, exc)
            break
        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            logger.warning("LLM response parse error (%s): %s — using rule-based fallback", model, exc)
            break

    return rule_based_assessment(patient_data)
