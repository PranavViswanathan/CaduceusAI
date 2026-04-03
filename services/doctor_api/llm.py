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
    conditions = ", ".join(patient_data.get("conditions", [])) or "None reported"
    medications = "; ".join(
        f"{m.get('name', '')} {m.get('dose', '')} {m.get('frequency', '')}"
        if isinstance(m, dict) else str(m)
        for m in patient_data.get("medications", [])
    ) or "None reported"
    allergies = ", ".join(patient_data.get("allergies", [])) or "None reported"
    symptoms = patient_data.get("symptoms") or "None reported"

    return (
        "You are a clinical decision support system. Analyze the following patient data and return "
        "a structured risk assessment as VALID JSON only. Do not include any text outside the JSON.\n\n"
        f"Patient: {patient_data.get('name', 'Unknown')}\n"
        f"Conditions: {conditions}\n"
        f"Current Medications: {medications}\n"
        f"Allergies: {allergies}\n"
        f"Symptoms: {symptoms}\n\n"
        "Return exactly this JSON structure:\n"
        '{"risks": ["risk1", "risk2"], "confidence": "low|medium|high", "summary": "narrative summary"}\n\n'
        "Confidence levels: high = clear clinical evidence, medium = some concern, low = minimal risk.\n"
        "Be specific about drug interactions, contraindications, and symptom red flags."
    )


def _parse_llm_json(raw: str) -> dict:
    raw = raw.strip()
    json_match = re.search(r"\{.*\}", raw, re.DOTALL)
    if json_match:
        return json.loads(json_match.group())
    return json.loads(raw)


async def get_risk_assessment(patient_data: dict) -> dict:
    prompt = _build_prompt(patient_data)

    for model in ("llama3", "mistral"):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
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
