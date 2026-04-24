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

On each request, `_model_priority_list()` calls `GET /api/tags` to discover what is available in Ollama, then returns an ordered list:

1. `medical-risk-ft` — fine-tuned adapter (used if registered after a successful training run)
2. `llama3` — base model (recommended, ~4.7 GB)
3. `mistral` — fallback base model (~4.1 GB)

All attempts share a 120-second async timeout (`httpx.AsyncClient`) — CPU inference of llama3 typically takes 30–90 s; GPU inference on `g4dn.xlarge` takes ~2–5 s. The `source` field in the response indicates which model was used (`"llm:medical-risk-ft"`, `"llm:llama3"`, etc.).

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

### Caching and DB-First Lookup

On each request the handler checks **two** caches before calling Ollama:

1. **Redis** — key `risk:{patient_id}`, TTL 300 s. A Redis hit returns instantly (~1 ms).
2. **Database** — if the Redis key is absent, the most recent `RiskAssessment` row for the patient is queried. If found, it is returned and re-cached in Redis. This means Ollama is only called the **first time** a patient's risk is ever assessed; all subsequent page views return the stored result in ~10 ms regardless of Redis TTL expiry.

A new Ollama call only happens after feedback explicitly invalidates the cache. When a doctor submits feedback (`POST /v1/doctor/patients/{id}/feedback`), the Redis key for that patient is **immediately deleted** (`redis.delete(f"risk:{patient_id}")`). This ensures the next risk request reflects the updated clinical context rather than serving a stale cached result.

The `version` counter on `RiskAssessment` rows still increments on each genuinely new LLM call, preserving the full assessment history for retraining reference.

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

The feedback loop is the mechanism by which clinician disagreements with LLM outputs feed back into model improvement. The full pipeline runs automatically via the `retrain-worker` Docker service.

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

Feedback with `action = agree` is stored in the database but **not** queued for retraining. The LangGraph agent's `retraining_trigger_node` also pushes to the same queue when `feedback_score` falls below the configured threshold (default 0.4).

### 2. Buffer Drain

The internal endpoint `POST /v1/doctor/retrain/trigger` (requires `X-Internal-Key`) pops all items from Redis and appends them to `data/retrain_buffer.jsonl`:

```bash
curl -X POST http://localhost:8002/v1/doctor/retrain/trigger \
  -H "X-Internal-Key: <INTERNAL_API_KEY>"
```

### 3. LoRA Fine-Tuning (`scripts/retrain_loop.py`)

`retrain_loop.py` executes the full training pipeline. It runs continuously inside the `retrain-worker` container, polling every `RETRAIN_POLL_INTERVAL_SECONDS` (default 5 minutes). It can also be invoked manually:

```bash
python3 scripts/retrain_loop.py
```

The pipeline only proceeds once the buffer reaches `MIN_RETRAIN_BATCH` items (default 5). If the threshold is not met the buffer is left untouched and the script exits cleanly.

#### Step-by-step

| Step | What happens |
|---|---|
| **Batch check** | Exits early if `len(buffer) < MIN_RETRAIN_BATCH` |
| **MLflow run start** | Opens an MLflow run in the `medical-risk-ft` experiment (creates the experiment on first run). All subsequent steps log into this run. MLflow calls are wrapped in try/except — if the server is unavailable, training proceeds without logging. |
| **Dataset construction** | For each buffer item, queries `risk_assessments` and `patient_intake` tables via `assessment_id`. Builds an Alpaca-format `{instruction, input, output}` example. `override` feedback uses the doctor's reason as the corrected `summary`; `flag` feedback appends a clinical note to the original assessment. Malformed JSONL lines are skipped with a warning rather than crashing. |
| **LoRA training** | Loads `TinyLlama/TinyLlama-1.1B-Chat-v1.0` from HuggingFace (cached in `hf_cache` Docker volume). Applies PEFT `LoraConfig(r=8, lora_alpha=16)` targeting `q_proj`, `v_proj`, `k_proj`, `o_proj`. Trains for `LORA_EPOCHS` epochs (default 2) on CPU with `learning_rate=2e-4`. |
| **Merge** | Calls `peft_model.merge_and_unload()` to fold adapter weights into the base model. Saves the merged model to `/app/models/runs/<version>/merged/`. |
| **Eval gate** | Runs the merged model against 5 hardcoded clinical scenarios (diabetic + hypertension, Warfarin + NSAID, SSRI + MAOI, Metformin + contrast, healthy patient). Each scenario checks that the model returns valid JSON with `risks` (list), `confidence` (low/medium/high), and `summary` (non-empty string). **The model is promoted only if all 5 scenarios pass (pass rate = 100%).** If the gate fails, the run is logged with `"status": "eval_failed"` and the buffer is preserved for retry. |
| **GGUF conversion** | Runs `llama.cpp`'s `convert_hf_to_gguf.py` on the merged model to produce a quantized `model.gguf` (q8_0). Skipped gracefully if `llama.cpp` is not available. |
| **Ollama registration** | Calls `POST /api/create` on Ollama with a Modelfile pointing to the GGUF. Tags the result as both `medical-risk-ft:<version>` and `medical-risk-ft:latest`. Updates `active_model` in Redis to `medical-risk-ft:latest` so the API can read the current model name without an Ollama tag lookup. |
| **Model registry** | Appends a run record to `/app/models/registry.json` with version, paths, eval pass rate, action breakdown, override rate, and status (`success` / `eval_failed` / `failed`). |
| **MLflow logging** | Logs params (`base_model`, `lora_rank`, `lora_alpha`, `epochs`, `lr`, `items_used`, `examples_built`, `override_rate`, `fine_tuned_model_name`) and metrics (`eval_pass_rate`, `override_rate`, `items_used`, `examples_built`). On success: logs the GGUF artifact + LoRA adapter, registers the model in the MLflow model registry as `medical-risk-ft`, and transitions the new version to **Production** (archiving the previous Production version). On eval failure: logs the LoRA adapter artifact and registers with stage **Archived**. Run status is set to FINISHED or FAILED accordingly. |
| **Buffer clear** | Clears `retrain_buffer.jsonl` only on success. On failure the buffer is preserved for retry and the error is logged. |

#### LoRA configuration

| Hyperparameter | Default | Env var |
|---|---|---|
| Base model | `TinyLlama/TinyLlama-1.1B-Chat-v1.0` | `BASE_MODEL_NAME` |
| LoRA rank | 8 | `LORA_RANK` |
| LoRA alpha | 16 | `LORA_ALPHA` |
| Target modules | `q_proj`, `v_proj`, `k_proj`, `o_proj` | — |
| LoRA dropout | 0.05 | — |
| Epochs | 2 | `LORA_EPOCHS` |
| Learning rate | 2e-4 | `LORA_LR` |
| Batch size | 1 (grad accum 4) | — |
| Min batch size | 5 | `MIN_RETRAIN_BATCH` |
| Poll interval | 300 s | `RETRAIN_POLL_INTERVAL_SECONDS` |

### 4. Fine-Tuned Model Inference

After a successful training run, `doctor-api` automatically prefers the fine-tuned model. On each risk assessment request, `llm.py` calls `GET /api/tags` on Ollama, then tries models in this priority order:

```
medical-risk-ft  →  llama3  →  mistral  →  rule-based fallback
```

The fine-tuned model is only used if it is registered in Ollama. If GGUF conversion fails (e.g., no llama.cpp), inference continues with the base models unchanged — training output is still persisted in HuggingFace format under `/app/models/runs/<version>/`.

The `source` field on risk assessment responses reflects which model was used: `"llm:medical-risk-ft"`, `"llm:llama3"`, or `"rule_based"`.

### 5. MLflow Model Registry

Open **http://localhost:5001** to access the MLflow UI. The `medical-risk-ft` experiment records every training run with:

- **Parameters**: base model, LoRA hyperparameters, dataset size, override rate
- **Metrics**: eval pass rate, override rate, items used, examples built
- **Artifacts**: GGUF model file (for successful runs), LoRA adapter weights
- **Model registry**: the `medical-risk-ft` registered model shows all versions with their lifecycle stage (`Production` for the active model, `Archived` for previous or failed versions)

Stage transitions happen automatically during training. You can also promote, demote, or archive versions manually from the MLflow UI.

### 6. Monitoring Training Runs

```bash
# Check buffer depth and recent runs (requires doctor auth)
curl http://localhost:8002/v1/doctor/retrain/status \
  -H "Authorization: Bearer <token>"
```

Response:
```json
{
  "buffer_items_pending": 3,
  "total_runs": 2,
  "runs": [
    {
      "version": "20260410T120000Z",
      "status": "success",
      "items_used": 7,
      "examples_built": 7,
      "eval_pass_rate": 1.0,
      "action_breakdown": {"override": 5, "flag": 2},
      "override_rate": 0.7143,
      "ollama_model": "medical-risk-ft:20260410T120000Z",
      "base_model": "TinyLlama/TinyLlama-1.1B-Chat-v1.0",
      "epochs": 2
    }
  ]
}
```

The full run history is also written line-by-line to `data/retrain_log.jsonl`.

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

Uses a **two-stage fast path** before calling Ollama:

1. **Rule-based regex match** — two compiled patterns scan the query text instantly:
   - `_URGENT_PATTERNS`: chest pain, shortness of breath, can't breathe, unconscious, severe pain, stroke, emergency, etc.
   - `_COMPLEX_PATTERNS`: drug interaction, contraindication, differential diagnosis, polypharmacy, mechanism, etc.
   If either pattern matches, the node returns immediately (`routine` / `complex` / `urgent`) without any Ollama call — saving ~30 s on common queries.

2. **LLM triage** — only if the regex produces no match, the node calls Ollama with a structured prompt (`num_predict: 20`, `temperature: 0.1`) that defines the three categories in clinical terms. Expects a JSON response `{"classification": "..."}`. Falls back to `"complex"` (the safest default) if Ollama is unreachable or returns an unexpected label. Timeout: 30 s.

#### `rag_node`

Handles **routine** queries. Retrieves the top-3 semantically similar documents from the clinical knowledge base (`agent/knowledge_base.py`) using ChromaDB vector search (cosine similarity over `all-MiniLM-L6-v2` sentence-transformer embeddings), then prompts Ollama to answer grounded in that context. Returns `response` and `confidence`. Ollama options: `num_predict: 350`, `temperature: 0.2`. Timeout: 60 s.

The knowledge base contains 12 clinical reference paragraphs (hypertension, T2DM, sepsis, AF, AKI, pneumonia, opioids, etc.) stored in a ChromaDB ephemeral collection initialised at startup. Semantic matching means related concepts match even without exact keyword overlap (e.g., "blood pressure control" matches "hypertension management"). For production, swap `chromadb.EphemeralClient()` for `chromadb.PersistentClient()` (SQLite-backed) or `chromadb.HttpClient()` (separate Chroma server) to persist embeddings across restarts.

#### `reasoning_node`

Handles **complex** queries using chain-of-thought (CoT) prompting. The prompt instructs Ollama to reason step-by-step and produce a JSON object with `chain_of_thought`, `response`, and `confidence`. Ollama options: `num_predict: 500`, `temperature: 0.2`. Timeout: 60 s. If `confidence < 0.5`, the graph routes to `escalation_node`.

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

### Clinical Knowledge Base (ChromaDB)

#### File: `services/doctor_api/agent/knowledge_base.py`

The knowledge base is a ChromaDB collection that stores 12 clinical reference paragraphs as dense vector embeddings. It is initialised once at process startup — all documents are embedded and loaded into memory before the first request is served.

**Setup:**

```python
import chromadb
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

_client = chromadb.EphemeralClient()
_collection = _client.get_or_create_collection(
    name="clinical_kb",
    embedding_function=DefaultEmbeddingFunction(),  # all-MiniLM-L6-v2 via ONNX
    metadata={"hnsw:space": "cosine"},
)
_collection.add(documents=_DOCUMENTS, ids=[f"doc_{i}" for i in range(len(_DOCUMENTS))])
```

**Retrieval:**

```python
def retrieve(query: str, k: int = 3) -> list[str]:
    results = _collection.query(query_texts=[query], n_results=min(k, len(_DOCUMENTS)))
    return results["documents"][0]
```

**Embedding model:** `all-MiniLM-L6-v2` (loaded via ONNX by ChromaDB's `DefaultEmbeddingFunction`; no separate model server required).

**Similarity metric:** Cosine distance (HNSW index). Semantic matching means queries like "blood pressure control" correctly retrieve the hypertension management document even without exact keyword overlap.

**Knowledge base contents:**

| # | Topic |
|---|---|
| 1 | Hypertension management (first-line agents, DASH diet, BP targets) |
| 2 | Type 2 Diabetes (Metformin, HbA1c targets, SGLT-2/GLP-1 add-on) |
| 3 | Chest pain differential (STEMI/NSTEMI, HEART score) |
| 4 | Drug interactions — anticoagulants (Warfarin + NSAIDs/ciprofloxacin) |
| 5 | Serotonin syndrome (SSRI/MAOI combinations, management) |
| 6 | Metformin + contrast media (hold protocol, eGFR threshold) |
| 7 | Community-acquired pneumonia (CURB-65, antibiotic selection) |
| 8 | Acute kidney injury (causes, management, dialysis indications) |
| 9 | Asthma exacerbation (SABA, corticosteroids, intubation criteria) |
| 10 | Sepsis-3 (hour-1 bundle, vasopressors, lactate threshold) |
| 11 | Atrial fibrillation (rate vs. rhythm control, CHA₂DS₂-VASc, DOACs) |
| 12 | Opioid dosing and safety (morphine equivalents, naloxone co-prescribing) |

**Upgrading for production:**

| Use case | Client |
|---|---|
| Development / single process | `chromadb.EphemeralClient()` (in-memory, current default) |
| Persistent local storage | `chromadb.PersistentClient(path="/data/chroma")` |
| Shared across replicas | `chromadb.HttpClient(host="chroma", port=8000)` (requires a Chroma server container) |

To add new clinical documents, append to `_DOCUMENTS` and redeploy — the collection is rebuilt on startup.

---

### Agent Response Cache

`agent/router.py` caches non-escalated agent responses in Redis to avoid redundant LLM calls for identical queries. The cache key is a 16-character SHA-256 prefix of the lowercased query + optional `patient_id`. Cache TTL: 300 s.

```
cache_key = "agent:" + sha256(f"{query.lower().strip()}|{patient_id or ''}").hexdigest()[:16]
```

Repeat queries from any doctor hit the cache and return in ~1 ms. Escalated responses are **not** cached — every escalation produces a new `AgentEscalation` DB record. The cache is cluster-shared via Redis, so all doctor-api replicas benefit.

---

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

---

## Observability

All Ollama calls and LangGraph agent nodes are instrumented with **OpenTelemetry**. Spans and metrics are exported via OTLP/HTTP to the OTel Collector, which forwards traces to Jaeger and exposes metrics to Prometheus (scraped by Grafana).

### Span reference

| Function / Node | Span name | Key attributes |
|---|---|---|
| `get_risk_assessment()` | `ollama.risk_assessment` | `ollama.operation`, `ollama.model`, `ollama.model_count`, `ollama.fallback` |
| `generate_care_plan()` | `ollama.care_plan` | `ollama.operation`, `ollama.model`, `ollama.fallback` |
| `assess_checkin_urgency()` | `ollama.urgency_assessment` | `ollama.operation`, `ollama.model`, `ollama.fallback` |
| `triage_node` | `agent.triage` | `agent.node`, `agent.query_type` |
| `rag_node` | `agent.rag` | `agent.node`, `agent.docs_retrieved`, `agent.confidence` |
| `reasoning_node` | `agent.reasoning` | `agent.node`, `agent.confidence` |
| `escalation_node` | `agent.escalation` | `agent.node`, `agent.query_type`, `agent.outcome` |
| `retraining_trigger_node` | `agent.retraining_trigger` | `agent.node`, `agent.retrain_enqueued` |

All Ollama HTTP calls also produce a child `HTTP POST` span from HTTPX auto-instrumentation. The parent custom span provides the clinical context (which operation the call serves); the child span provides raw HTTP timing and status.

### Prometheus metrics

| Metric | Type | Description |
|---|---|---|
| `medical_ai_ollama_request_duration_seconds` | Histogram | Wall-clock time from sending the Ollama POST to receiving a valid parsed response, labelled by `ollama_model` and `ollama_operation` |
| `medical_ai_ollama_fallback_total` | Counter | Incremented each time a rule-based fallback is used instead of Ollama, labelled by `ollama_operation` |
| `medical_ai_agent_node_duration_seconds` | Histogram | End-to-end duration of each LangGraph node including any Ollama call it makes, labelled by `agent_node` |

The OTel Collector's `spanmetrics` connector additionally derives `medical_ai_traces_spanmetrics_calls_total` and `medical_ai_traces_spanmetrics_duration_milliseconds` from every span — covering DB queries, Redis commands, and HTTP routes without any additional instrumentation code.

### Viewing traces

Open Jaeger at **http://localhost:16686** and select service `doctor_api` or `postcare_api`. Each agent query produces a trace with the full node execution chain visible as nested spans. The `ollama.fallback = true` attribute on a span indicates the LLM was unavailable and the rule-based path was taken.

### Viewing metrics

Open Grafana at **http://localhost:3030** (admin / admin) → **Medical AI Platform** dashboard. The *Ollama Inference Duration* panel shows p50 and p95 latency per operation, and the *Ollama Fallback Rate* panel shows how often the rule engine activates — a sustained non-zero rate indicates Ollama connectivity issues.
