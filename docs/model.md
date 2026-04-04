# AI Model & LLM Integration

## Overview

The platform uses **Ollama** for fully local LLM inference. No data ever leaves the host machine. Two models are supported: `llama3` (recommended, ~4.7 GB) and `mistral` (~4.1 GB). Both APIs that call the LLM implement automatic rule-based fallbacks so the system remains functional even when Ollama is unavailable or times out.

---

## Where LLM Is Used

| Service | Function | Input | Output |
|---|---|---|---|
| `doctor-api` | Risk assessment | Patient intake (conditions, meds, allergies, symptoms) | `risks[]`, `confidence`, `summary` |
| `postcare-api` | Care plan generation | Visit notes | `follow_up_date`, `medications_to_monitor[]`, `lifestyle_recommendations[]`, `warning_signs[]` |
| `postcare-api` | Urgency classification | Symptom report + care plan warning signs | `routine` / `monitor` / `escalate` |

---

## Risk Assessment (doctor-api)

### File: `services/doctor_api/llm.py`

### Prompt Construction

The function `get_risk_assessment()` builds a structured clinical decision support prompt:

```
You are a clinical decision support AI.
Given the following patient data, identify clinical risks.

Patient Data:
- Conditions: {conditions}
- Medications: {medications}
- Allergies: {allergies}
- Symptoms: {symptoms}

Return JSON only:
{
  "risks": ["risk1", "risk2"],
  "confidence": "low|medium|high",
  "summary": "brief clinical narrative"
}
```

### Model Cascade

1. Try `llama3` first (faster, recommended)
2. On model-not-found error, retry with `mistral`
3. Both attempts share the same 10-second async timeout (`httpx.AsyncClient`)

### JSON Extraction

After receiving the raw Ollama response, the function uses regex to extract the first valid JSON object from the text (Ollama sometimes wraps JSON in markdown fences or adds prose). Extraction failures fall through to the rule-based fallback.

### Rule-Based Fallback

If Ollama is unavailable, times out, or returns unparseable output, `get_risk_assessment()` runs a deterministic drug-interaction checker:

| Drug Combo | Risk Flagged |
|---|---|
| Warfarin + any NSAID | Increased bleeding risk |
| SSRI + MAOI | Serotonin syndrome risk |
| Metformin + contrast dye | Lactic acidosis risk |

The fallback returns:
```json
{
  "risks": ["<identified interaction>"],
  "confidence": "low",
  "summary": "Rule-based assessment — Ollama unavailable.",
  "source": "rule_based"
}
```

If no known interactions are found, it returns a generic low-confidence warning.

### Caching

Successful assessments are cached in Redis under key `risk:{patient_id}` with a 300-second TTL. Cache misses are treated as no-ops (the assessment is always recomputed on a miss; the cache is best-effort).

When a doctor submits feedback (`POST /v1/doctor/patients/{id}/feedback`), the cache key for that patient is **immediately deleted** (`redis.delete(f"risk:{patient_id}")`). This ensures the next risk request reflects the updated clinical context rather than serving a stale cached result.

---

## Care Plan Generation (postcare-api)

### File: `services/postcare_api/llm.py` — `generate_care_plan()`

### Prompt

```
You are a medical care plan generator.
Given the following visit notes, generate a structured care plan.

Visit Notes:
{visit_notes}

Return JSON only:
{
  "follow_up_date": "YYYY-MM-DD",
  "medications_to_monitor": ["med1", "med2"],
  "lifestyle_recommendations": ["rec1", "rec2"],
  "warning_signs": ["sign1", "sign2"]
}
```

### Fallback

If Ollama fails, a static safe template is returned:

```json
{
  "follow_up_date": "<today + 14 days>",
  "medications_to_monitor": [],
  "lifestyle_recommendations": [
    "Rest and adequate hydration",
    "Avoid strenuous activity",
    "Follow prescribed medication schedule"
  ],
  "warning_signs": [
    "Fever above 101°F",
    "Chest pain or shortness of breath",
    "Sudden severe headache",
    "Signs of allergic reaction"
  ]
}
```

---

## Urgency Assessment (postcare-api)

### File: `services/postcare_api/llm.py` — `assess_checkin_urgency()`

### Prompt

```
You are a medical triage assistant.
A patient has submitted the following symptom report.
Based on their care plan warning signs, classify the urgency.

Care Plan Warning Signs:
{warning_signs}

Patient Symptom Report:
{symptom_report}

Return JSON only:
{
  "urgency": "routine|monitor|escalate",
  "reason": "brief explanation"
}
```

### Rule-Based Fallback

Keyword scanning in the symptom report text (case-insensitive):

| Urgency | Trigger Keywords |
|---|---|
| `escalate` | chest pain, can't breathe, unconscious, severe pain, stroke |
| `monitor` | fever, vomiting, dizzy, infection, bleeding |
| `routine` | (none of the above matched) |

### Escalation Trigger

If urgency is `escalate`:
1. An `Escalation` row is written to PostgreSQL
2. The escalation is pushed to Redis `escalation_queue`
3. The doctor portal polls `GET /v1/escalations/pending` every 60 seconds and shows a red alert banner

---

## Ollama Configuration

Ollama is started as a Docker service and is accessible at `http://ollama:11434` inside the Docker network (configured via `OLLAMA_URL` in `.env`).

### Automatic Model Setup

Models are pulled automatically on first boot by the `ollama-init` Docker Compose service:

```yaml
ollama-init:
  image: ollama/ollama
  volumes:
    - ollama_data:/root/.ollama
  depends_on:
    ollama:
      condition: service_healthy
  entrypoint: >
    sh -c "
      ollama pull llama3 --host http://ollama:11434 &&
      ollama pull mistral --host http://ollama:11434
    "
  restart: "no"
```

Model weights are stored in the `ollama_data` Docker volume. On subsequent `docker compose up` runs the volume already contains the weights, so `ollama-init` exits immediately without re-downloading.

### Manual Pull (if needed)

```bash
# Pull into a running stack
docker exec -it medical-ai-platform-ollama-1 ollama pull llama3
docker exec -it medical-ai-platform-ollama-1 ollama pull mistral
```

### Async HTTP Client

All Ollama calls use `httpx.AsyncClient` with a 10-second timeout:

```python
async with httpx.AsyncClient(timeout=10.0) as client:
    response = await client.post(
        f"{settings.OLLAMA_URL}/api/generate",
        json={"model": "llama3", "prompt": prompt, "stream": False}
    )
```

---

## Retraining Pipeline

The feedback loop is the mechanism by which clinician disagreements with LLM outputs feed back into model improvement.

### 1. Feedback Collection

When a doctor submits feedback with `action = override` or `action = flag`, `doctor-api` pushes a JSON event to the Redis `retrain_queue`:

```json
{
  "patient_id": "<uuid>",
  "doctor_id": "<uuid>",
  "action": "override",
  "reason": "Assessment missed drug interaction",
  "assessment_id": "<uuid>",
  "timestamp": "2026-04-03T12:00:00Z"
}
```

Feedback with `action = agree` is stored in the database but **not** queued for retraining — agreement is a positive signal that doesn't require model correction.

### 2. Buffer Drain

The internal endpoint `POST /v1/doctor/retrain/trigger` (requires `X-Internal-Key`) pops all items from Redis and appends them to `data/retrain_buffer.jsonl`:

```bash
curl -X POST http://localhost:8002/v1/doctor/retrain/trigger \
  -H "X-Internal-Key: <INTERNAL_API_KEY>"
```

### 3. Retrain Loop Script

`scripts/retrain_loop.py` processes the buffer:

1. Reads `data/retrain_buffer.jsonl` line by line
2. Parses each feedback event
3. Prints a summary: patient_id, action, reason, assessment_id
4. Counts action breakdown (overrides vs flags)
5. Appends a timestamped run record to `data/retrain_log.jsonl`
6. Clears `retrain_buffer.jsonl`

```bash
python3 scripts/retrain_loop.py
```

### 4. Production LoRA Fine-Tuning (Documented in Script)

The script's docstring describes the full production pipeline the retrain loop is designed to feed into:

| Step | Detail |
|---|---|
| **Data reconstruction** | Re-fetch original prompt + response from `risk_assessments` table using `assessment_id` |
| **Alpaca formatting** | Convert each corrected pair to `{instruction, input, output}` |
| **Batch threshold** | Accumulate ≥ 50 examples before triggering a training run |
| **LoRA fine-tuning** | Hugging Face PEFT, target modules `q_proj` + `v_proj`, 4-bit quantization |
| **Evaluation** | F1 on urgency classification, ROUGE on narrative, false-negative rate on high-risk cases |
| **Canary rollout** | 10 % traffic for 24 hours before full promotion |
| **Rollback** | Every version links to its training data, eval results, and contributing feedback items |

---

## Assessment Versioning

Every call to `GET /v1/doctor/patients/{id}/risk` stores a new `RiskAssessment` row with an incrementing `version` integer. This means:

- Doctors always see the most recent assessment
- All historical assessments (and their `source`: `llm` or `rule_based`) are retained
- Feedback rows reference `assessment_id`, so retraining can always reconstruct the exact prompt/response pair that was overridden

---

## Confidence Levels

| Level | Meaning |
|---|---|
| `high` | Ollama returned a well-formed response with multiple coherent risks |
| `medium` | Ollama returned a response but with limited clinical detail |
| `low` | Rule-based fallback was used, or Ollama output was sparse |

Confidence is displayed in the doctor portal's risk panel to help clinicians calibrate how much weight to place on the AI assessment.
