# AI Model & LLM Integration

## Overview

The platform uses **Ollama** for fully local LLM inference. No data ever leaves the host machine (or VPC in the AWS deployment). Two models are supported: `llama3` (recommended, ~4.7 GB) and `mistral` (~4.1 GB). Both APIs that call the LLM implement automatic rule-based fallbacks so the system remains functional even when Ollama is unavailable or times out.

---

## Where LLM Is Used

| Service | Function | Input | Output |
|---|---|---|---|
| `doctor-api` | Risk assessment | Patient intake (conditions, meds, allergies, symptoms) | `risks[]`, `confidence`, `summary` |
| `doctor-api` | Agent triage | Clinical query text | `routine` / `complex` / `urgent` |
| `doctor-api` | Agent RAG response | Query + retrieved KB docs | `response`, `confidence` |
| `doctor-api` | Agent chain-of-thought | Complex clinical query | `chain_of_thought`, `response`, `confidence` |
| `postcare-api` | Care plan generation | Visit notes | `follow_up_date`, `medications_to_monitor[]`, `lifestyle_recommendations[]`, `warning_signs[]` |
| `postcare-api` | Urgency classification | Symptom report + care plan warning signs | `routine` / `monitor` / `escalate` |

---

## Risk Assessment (doctor-api)

### File: `services/doctor_api/llm.py`

### Prompt Construction

The function `get_risk_assessment()` builds a concise structured prompt designed to keep the model's output strictly JSON. Medication names only (no dose/frequency) are included to reduce output length and improve parse reliability:

```
You are a clinical risk assessment tool. Reply with ONLY a JSON object — no prose, no markdown.
Required format: {"risks":["short risk 1","short risk 2"],"confidence":"low","summary":"one sentence"}
confidence must be exactly: low, medium, or high.

Conditions: {conditions}
Medications: {medication names}
Allergies: {allergies}
Symptoms: {symptoms}

JSON:
```

### Model Cascade

1. Try `llama3` first (faster, recommended)
2. On model-not-found error, retry with `mistral`
3. Both attempts share a 120-second async timeout (`httpx.AsyncClient`) — CPU inference of llama3 typically takes 30–90 s; GPU inference on `g4dn.xlarge` takes ~2–5 s

### JSON Extraction

After receiving the raw Ollama response, the function uses regex to extract the first valid `{...}` JSON object from the text. Control characters (except tabs, newlines, and carriage returns) are stripped before parsing to handle common LLM output quirks. Extraction or parse failures fall through to the rule-based fallback.

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

### Local (Docker Compose)

Ollama is started as a Docker service and is accessible at `http://ollama:11434` inside the Docker network (configured via `OLLAMA_URL` in `.env`).

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

The `ollama` service healthcheck uses `ollama list` rather than `curl`, because the `ollama/ollama` image does not include `curl`.

```bash
# Manual pull if needed
docker compose exec ollama ollama pull llama3
docker compose exec ollama ollama pull mistral
```

### AWS (EC2 g4dn.xlarge)

In the AWS deployment, Ollama runs on an EC2 `g4dn.xlarge` instance with an NVIDIA T4 GPU (16 GB VRAM). This is provisioned by `terraform/ollama.tf`.

| Spec | Value |
|---|---|
| Instance type | `g4dn.xlarge` (configurable via `ollama_instance_type`) |
| GPU | NVIDIA T4 (16 GB VRAM) |
| vCPU | 4 |
| RAM | 16 GB |
| Storage | 100 GB gp3 EBS (configurable via `ollama_volume_size`) |
| OS | Amazon Linux 2023 |
| Inference speed | ~2–5 s per request (vs 30–90 s on CPU) |

Bootstrap process (user-data script):
1. Install CUDA toolkit + NVIDIA drivers (dnf)
2. Install Ollama via official install script
3. Create `ollama` system user and `/var/lib/ollama/models` directory
4. Register Ollama as a systemd service (`OLLAMA_HOST=0.0.0.0`)
5. Pull `llama3` and `mistral` into `/var/lib/ollama/models` (~9 GB total, runs in background after boot)

The EBS root volume has `delete_on_termination = false` and the instance has `prevent_destroy = true` in Terraform to prevent accidental model re-download (~10 minutes, ~9 GB). Use AWS SSM Session Manager to access the instance without SSH:

```bash
aws ssm start-session --target <ollama-instance-id>

# Check Ollama service status
systemctl status ollama

# Verify models are loaded
curl http://localhost:11434/api/tags

# Monitor model pull progress (on first boot)
tail -f /var/log/ollama-init.log
```

ECS tasks reach Ollama via its private IP address, which Terraform resolves automatically:

```hcl
# In ecs.tf
ollama_url = "http://${aws_instance.ollama.private_ip}:11434"
```

---

## Async HTTP Client

All Ollama calls use `httpx.AsyncClient` with a 120-second timeout. The long timeout accommodates CPU-only inference on development machines; GPU inference on AWS typically completes in 2–5 seconds.

```python
async with httpx.AsyncClient(timeout=120.0) as client:
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

Feedback with `action = agree` is stored in the database but **not** queued for retraining.

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

## LangGraph Agentic Orchestration (doctor-api)

### Files: `services/doctor_api/agent/`

The agent layer is a LangGraph `StateGraph` that routes each clinical query through a pipeline of five specialised nodes. It is exposed via `POST /v1/agent/query` and reuses the existing Ollama client, PostgreSQL session, Redis client, and PHI encryption — no new connections are created.

### Typed State

All inter-node data flows through `AgentState` (a `TypedDict`) defined in `agent/state.py`. Key fields:

| Field | Type | Set by |
|---|---|---|
| `query` | str | router (request input) |
| `query_type` | str | triage_node |
| `rag_context` | list[str] | rag_node |
| `chain_of_thought` | str | reasoning_node |
| `response` | str | rag_node / reasoning_node / escalation_node |
| `confidence` | float | rag_node / reasoning_node |
| `requires_escalation` | bool | escalation_node |
| `escalation_id` | str \| None | escalation_node |
| `feedback_score` | float \| None | router (request input) |

### Graph Topology

```
triage_node  ← entry point
    │
    ├── "routine"  ──→  rag_node  ──────────────────→  retraining_trigger_node  →  END
    │
    ├── "complex"  ──→  reasoning_node  ──(conf ≥ 0.5)──→  retraining_trigger_node  →  END
    │                        │
    │                        └──(conf < 0.5)──→  escalation_node  →  END
    │
    └── "urgent"  ──────────────────────────────────→  escalation_node  →  END
```

Audit log entries are written only at terminal nodes (`retraining_trigger_node` and `escalation_node`) — one entry per request.

### Node Reference

#### `triage_node`

Calls Ollama with a structured prompt that defines `routine`, `complex`, and `urgent` in clinical terms. Expects a JSON response `{"classification": "..."}`. Falls back to `"complex"` (the safest default) if Ollama is unreachable or returns an unexpected label. Timeout: 30 s.

#### `rag_node`

Handles **routine** queries. Retrieves the top-3 matching documents from an in-memory medical knowledge base (`agent/knowledge_base.py`) using term-frequency scoring, then prompts Ollama to answer grounded in that context. Returns `response` and `confidence`. Timeout: 60 s.

The knowledge base contains 12 clinical reference paragraphs (hypertension, T2DM, sepsis, AF, AKI, pneumonia, opioids, etc.) and is designed to be replaced with a proper vector store (pgvector, Chroma) in production.

#### `reasoning_node`

Handles **complex** queries using chain-of-thought (CoT) prompting. The prompt instructs Ollama to reason step-by-step and produce a JSON object with `chain_of_thought`, `response`, and `confidence`. Timeout: 120 s. If `confidence < 0.5`, the graph routes to `escalation_node`.

#### `escalation_node`

Handles **urgent** queries and low-confidence complex queries. Creates an `AgentEscalation` record in PostgreSQL with the raw query stored PHI-encrypted (Fernet/AES-256 via the existing `encrypt()` function). Returns a `"pending clinician review"` response. Writes the terminal audit log entry.

#### `retraining_trigger_node`

Runs at the end of every non-escalation path. Checks whether `feedback_score` (passed in from the API request) falls below `RETRAIN_SCORE_THRESHOLD` (default 0.4, overridable via env var). If so, pushes a payload to the Redis `retrain_queue`:

```json
{
  "patient_id": "<uuid>",
  "assessment_id": "<uuid>",
  "feedback_score": 0.2,
  "action": "agent_low_score",
  "timestamp": "2026-04-10T12:00:00Z"
}
```

Always writes the terminal audit log entry regardless of whether a retrain job was enqueued.

### LangGraph Studio

The compiled graph is exported as the module-level variable `graph` in `agent/graph.py`. The `langgraph.json` config at the service root points LangGraph Studio to it:

```json
{
  "graphs": { "caduceus_agent": "./agent/graph.py:graph" },
  "env": ".env"
}
```

The `GET /v1/agent/graph` endpoint returns the same graph structure as JSON for custom visualisation tooling.

### Dependencies Injected via RunnableConfig

Nodes do not open new database or Redis connections. The FastAPI-managed `db` session and Redis client are injected via `config["configurable"]` at invocation time:

```python
result = await graph.ainvoke(
    initial_state,
    config={"configurable": {"db": db, "redis": redis}},
)
```

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

---

## Inference Performance

| Environment | Hardware | Typical latency |
|---|---|---|
| Local (Docker) | CPU only (no GPU) | 30–90 s per request |
| AWS (`g4dn.xlarge`) | NVIDIA T4 GPU | 2–5 s per request |
| AWS (`g4dn.2xlarge`) | NVIDIA T4 GPU (2×) | 1–3 s per request |

For production workloads with many concurrent doctors, consider:
- Upgrading to `g4dn.2xlarge` or `g4dn.12xlarge` for more VRAM (set `ollama_instance_type` in `terraform.tfvars`)
- Running multiple Ollama instances behind an internal load balancer
- Moving to a managed inference endpoint (AWS Bedrock) if data-residency requirements allow it — this would require changes to `llm.py`
