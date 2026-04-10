# API Reference

## Swagger / Interactive Docs

When running locally, interactive Swagger docs are available at:

| Service | Docs URL |
|---|---|
| Patient API | http://localhost:8001/docs |
| Doctor API | http://localhost:8002/docs |
| PostCare API | http://localhost:8003/docs |

All endpoints are versioned under the `/v1/` prefix. Authentication is cookie-based — the login endpoint sets an httpOnly cookie that the browser sends automatically. The Swagger UI Authorize button (Bearer token fallback) still works for interactive testing.

---

## AWS Path-Based Routing

In the AWS deployment (see [Architecture](architecture.md)), all services sit behind a single ALB. The default path prefixes used for ALB routing are:

| Service | ALB path prefix | Local port |
|---|---|---|
| patient-api | `/api/patient/*` | `:8001` |
| doctor-api | `/api/doctor/*` | `:8002` |
| postcare-api | `/api/postcare/*` | `:8003` |
| patient-portal | default (root) | `:3000` |
| doctor-portal | `doctor.<domain>` host header | `:3001` |

The ALB strips the prefix before forwarding to the target group, so the application code is unchanged — `/v1/auth/token` remains `/v1/auth/token` regardless of environment.

Swagger docs are not exposed through the ALB in production. Use an SSM session or VPN to reach the service ports directly if needed.

---

## Patient API (port 8001 / `/api/patient`)

### Authentication

#### `POST /v1/auth/register`

Create a patient account.

**Request body**:
```json
{
  "email": "patient@example.com",
  "password": "Password123",
  "name": "Jane Doe",
  "dob": "1990-05-14",
  "sex": "female",
  "phone": "+1-555-0100"
}
```

Validation rules: `dob` must be `YYYY-MM-DD`; `sex` must be one of `male`, `female`, `other`, `prefer_not_to_say`; `name` 2–100 characters; `password` minimum 8 characters.

**Response** `201`:
```json
{
  "id": "<uuid>",
  "email": "patient@example.com",
  "name": "Jane Doe"
}
```

---

#### `POST /v1/auth/token`

Login and receive an httpOnly session cookie. Uses OAuth2 password form fields.

**Request** (form data):
```
username=patient@example.com
password=Password123
```

**Response** `200` — sets `patient_access_token` httpOnly cookie; body:
```json
{
  "patient_id": "<uuid>",
  "token_type": "cookie"
}
```

Rate limited to **5 requests/minute per IP**.

---

#### `POST /v1/auth/logout`

Clear the session cookie.

**Response** `200`:
```json
{ "message": "Logged out" }
```

---

### Patients

#### `POST /v1/patients/intake`

Submit a health intake. Requires authenticated session (cookie or `Authorization: Bearer`).

**Request body**:
```json
{
  "conditions": ["Type 2 Diabetes", "Hypertension"],
  "medications": [
    {"name": "Metformin", "dose": "500mg", "frequency": "twice daily"},
    {"name": "Lisinopril", "dose": "10mg", "frequency": "once daily"}
  ],
  "allergies": ["Penicillin"],
  "symptoms": "Increased thirst, frequent urination, mild headache"
}
```

`symptoms` must be 10–5000 characters.

**Response** `201`:
```json
{
  "id": "<uuid>",
  "patient_id": "<uuid>",
  "submitted_at": "2026-04-03T12:00:00Z"
}
```

---

#### `GET /v1/patients/{patient_id}`

Retrieve patient profile and latest intake. Session must belong to the same patient (self-only).

**Response** `200`:
```json
{
  "id": "<uuid>",
  "email": "patient@example.com",
  "name": "Jane Doe",
  "dob": "1990-05-14",
  "sex": "female",
  "phone": "+1-555-0100",
  "latest_intake": {
    "conditions": ["Type 2 Diabetes"],
    "medications": [...],
    "allergies": ["Penicillin"],
    "symptoms": "...",
    "submitted_at": "2026-04-03T12:00:00Z"
  }
}
```

---

#### `GET /health`

**Response** `200`:
```json
{ "status": "ok" }
```

or `503`:
```json
{ "status": "degraded", "details": { "postgres": "error: ...", "redis": "ok" } }
```

---

## Doctor API (port 8002 / `/api/doctor`)

All endpoints under `/v1/doctor/` require a `doctor_access_token` httpOnly cookie (or `Authorization: Bearer` fallback) where the token carries `role="doctor"`.

### Authentication

#### `POST /v1/auth/register`

Register a doctor account.

**Request body**:
```json
{
  "email": "doctor@hospital.com",
  "password": "Password123",
  "name": "Dr. Smith",
  "specialty": "Internal Medicine"
}
```

**Response** `201`:
```json
{ "id": "<uuid>", "email": "doctor@hospital.com", "name": "Dr. Smith" }
```

---

#### `POST /v1/auth/token`

Doctor login. Sets `doctor_access_token` httpOnly cookie.

**Response** `200`:
```json
{ "doctor_id": "<uuid>", "token_type": "cookie" }
```

Rate limited to **5 requests/minute per IP**.

---

#### `POST /v1/auth/logout`

Clear the doctor session cookie.

**Response** `200`:
```json
{ "message": "Logged out" }
```

---

### Patients

#### `GET /v1/doctor/patients`

List all patients with their latest intake timestamp.

**Response** `200`:
```json
[
  {
    "id": "<uuid>",
    "name": "Jane Doe",
    "email": "patient@example.com",
    "latest_intake_at": "2026-04-03T12:00:00Z"
  }
]
```

---

#### `GET /v1/doctor/patients/{patient_id}/risk`

Retrieve (or generate) an AI risk assessment for a patient.

Flow: check Redis cache → call Ollama → fall back to rule-based → store + cache result.

**Response** `200`:
```json
{
  "id": "<uuid>",
  "patient_id": "<uuid>",
  "version": 3,
  "risks": [
    "Drug interaction: Warfarin + Ibuprofen (increased bleeding risk)",
    "Uncontrolled hypertension risk given current medication load"
  ],
  "confidence": "medium",
  "summary": "Patient presents with moderate risk of bleeding event ...",
  "source": "llm",
  "created_at": "2026-04-03T12:00:00Z"
}
```

---

#### `POST /v1/doctor/patients/{patient_id}/feedback`

Submit clinician feedback on a risk assessment. Also invalidates the Redis cache for this patient's risk assessment (`risk:{patient_id}`).

**Request body**:
```json
{
  "action": "override",
  "reason": "Assessment missed known contraindication.",
  "assessment_id": "<uuid>"
}
```

`action` must be one of: `agree`, `override`, `flag`. `reason` is required for `override` and `flag` (1–2000 characters).

**Response** `201`:
```json
{ "id": "<uuid>", "action": "override", "created_at": "2026-04-03T12:01:00Z" }
```

If `action` is `override` or `flag`, the feedback is also pushed to the Redis `retrain_queue`.

---

### Escalations

#### `GET /v1/escalations/pending`

Returns all unacknowledged escalations.

**Response** `200`:
```json
[
  {
    "id": "<uuid>",
    "patient_id": "<uuid>",
    "checkin_id": "<uuid>",
    "acknowledged": false,
    "created_at": "2026-04-03T11:45:00Z"
  }
]
```

---

### Internal Endpoints

#### `POST /v1/doctor/retrain/trigger`

Drain the Redis retrain queue to `data/retrain_buffer.jsonl`. Requires `X-Internal-Key` header.

**Response** `200`:
```json
{ "drained": 12 }
```

---

#### `GET /health`

Same format as patient-api health response.

---

### Agent

The agent endpoints expose the LangGraph orchestration layer. All routes require a `doctor_access_token` cookie (or `Authorization: Bearer` fallback).

#### `POST /v1/agent/query`

Submit a clinical query to the five-node LangGraph agent. The agent automatically triages the query, selects the appropriate reasoning path (RAG, chain-of-thought, or escalation), and writes an audit log entry before returning.

**Request body**:
```json
{
  "query": "What is the first-line treatment for hypertension in a diabetic patient?",
  "patient_id": "<uuid>",
  "feedback_score": 0.2,
  "feedback_assessment_id": "<uuid>"
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `query` | String | Yes | The clinical question or instruction |
| `patient_id` | UUID | No | Attaches to audit and escalation records |
| `feedback_score` | Float 0.0–1.0 | No | Clinician score for a **prior** agent response. If below `RETRAIN_SCORE_THRESHOLD` (default 0.4), a retraining job is enqueued to Redis |
| `feedback_assessment_id` | UUID | No | Assessment UUID linked to the feedback score |

**Response** `200`:
```json
{
  "query_type": "routine",
  "response": "First-line antihypertensives for diabetic patients include ACE inhibitors (e.g. lisinopril) or ARBs...",
  "confidence": 0.82,
  "requires_escalation": false,
  "escalation_id": null,
  "chain_of_thought": null
}
```

| Field | Notes |
|---|---|
| `query_type` | `routine` / `complex` / `urgent` — set by triage_node |
| `response` | Final answer or `"This query has been flagged for clinician review."` when escalated |
| `confidence` | Float 0.0–1.0; `0.0` when escalated |
| `requires_escalation` | `true` if routed through escalation_node |
| `escalation_id` | UUID of the created `agent_escalations` record, or `null` |
| `chain_of_thought` | Step-by-step reasoning from reasoning_node, or `null` |

**Graph routing**:
- `routine` → RAG retrieval → retrain check → response
- `complex` → chain-of-thought reasoning → (confidence ≥ 0.5) → retrain check → response
- `complex` → chain-of-thought reasoning → (confidence < 0.5) → escalated
- `urgent` → escalated immediately

**Error** `503`: Agent temporarily unavailable (graph execution failure).

---

#### `GET /v1/agent/graph`

Return the LangGraph graph structure as JSON for developer tooling and LangGraph Studio visualisation. Requires a doctor session.

**Response** `200`: JSON object describing nodes, edges, and conditional routing as returned by LangGraph's built-in graph introspection (`graph.get_graph().to_json()`).

---

## PostCare API (port 8003 / `/api/postcare`)

### Care Plans

#### `POST /v1/careplan/generate`

Generate a structured care plan from visit notes. Requires `X-Internal-Key` header (internal service call only).

**Request body**:
```json
{
  "patient_id": "<uuid>",
  "visit_notes": "Patient presents with controlled T2DM. Adjust Metformin to 1000mg BD. Follow up in 2 weeks."
}
```

`visit_notes` must be 1–10000 characters.

**Response** `201`:
```json
{
  "id": "<uuid>",
  "patient_id": "<uuid>",
  "follow_up_date": "2026-04-17",
  "medications_to_monitor": ["Metformin"],
  "lifestyle_recommendations": ["Low-sugar diet", "30 minutes daily walking"],
  "warning_signs": ["Fever above 101°F", "Chest pain", "Shortness of breath"],
  "created_at": "2026-04-03T12:00:00Z"
}
```

---

#### `GET /v1/careplan/{patient_id}`

Retrieve the latest care plan for a patient. Requires authenticated doctor session.

**Response** `200`: same shape as the create response.

---

### Follow-up Check-ins

#### `POST /v1/followup/checkin`

Patient submits a symptom report. Urgency is assessed automatically. Requires patient or doctor session.

**Request body**:
```json
{
  "patient_id": "<uuid>",
  "symptom_report": "I have a fever of 102°F and feel very dizzy."
}
```

`symptom_report` must be 10–5000 characters.

**Response** `201`:
```json
{
  "id": "<uuid>",
  "patient_id": "<uuid>",
  "symptom_report": "...",
  "urgency": "escalate",
  "reason": "Reported fever exceeds care plan threshold; escalation created.",
  "created_at": "2026-04-03T12:05:00Z"
}
```

If `urgency == "escalate"`: an `Escalation` row is created and pushed to Redis `escalation_queue`.

---

### Escalations

#### `GET /v1/escalations/pending`

Unacknowledged escalations. Requires doctor session. Polled by doctor portal every 60 seconds.

**Response** `200`: list of escalation objects.

---

#### `POST /v1/escalations/{escalation_id}/acknowledge`

Mark an escalation as acknowledged. Requires doctor session.

**Response** `200`:
```json
{
  "id": "<uuid>",
  "acknowledged": true,
  "acknowledged_by": "<doctor_uuid>"
}
```

---

#### `GET /health`

Standard health check response.

---

## Error Responses

All APIs return consistent error shapes:

| Code | Meaning |
|---|---|
| `400` | Validation error (Pydantic) |
| `401` | Missing, expired, or invalid session |
| `403` | Correct format but wrong role or missing `X-Internal-Key` |
| `404` | Resource not found |
| `409` | Conflict (e.g. email already registered) |
| `429` | Rate limit exceeded |
| `503` | Database or downstream dependency unavailable |

```json
{ "detail": "Human-readable error message" }
```
