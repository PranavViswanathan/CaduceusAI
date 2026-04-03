# API Reference

Interactive Swagger docs are available when the stack is running:

| Service | Docs URL |
|---|---|
| Patient API | http://localhost:8001/docs |
| Doctor API | http://localhost:8002/docs |
| PostCare API | http://localhost:8003/docs |

---

## Patient API (port 8001)

### Authentication

#### `POST /auth/register`

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

**Response** `201`:
```json
{
  "id": "<uuid>",
  "email": "patient@example.com",
  "name": "Jane Doe"
}
```

---

#### `POST /auth/token`

Login and receive a JWT. Uses OAuth2 password form fields.

**Request** (form data):
```
username=patient@example.com
password=Password123
```

**Response** `200`:
```json
{
  "access_token": "<jwt>",
  "token_type": "bearer"
}
```

---

### Patients

#### `POST /patients/intake`

Submit a health intake. Requires `Authorization: Bearer <token>`.

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

**Response** `201`:
```json
{
  "id": "<uuid>",
  "patient_id": "<uuid>",
  "submitted_at": "2026-04-03T12:00:00Z"
}
```

---

#### `GET /patients/{patient_id}`

Retrieve patient profile and latest intake. Token must belong to the same patient (self-only).

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

## Doctor API (port 8002)

All endpoints under `/doctor/` require `Authorization: Bearer <token>` where the token carries `role="doctor"`.

### Authentication

#### `POST /auth/register`

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

#### `POST /auth/token`

Doctor login. Same OAuth2 password form as patient API.

**Response** `200`:
```json
{ "access_token": "<jwt>", "token_type": "bearer" }
```

---

### Patients

#### `GET /doctor/patients`

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

#### `GET /doctor/patients/{patient_id}/risk`

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

#### `POST /doctor/patients/{patient_id}/feedback`

Submit clinician feedback on a risk assessment.

**Request body**:
```json
{
  "action": "override",
  "reason": "Assessment missed known contraindication.",
  "assessment_id": "<uuid>"
}
```

`action` must be one of: `agree`, `override`, `flag`.

**Response** `201`:
```json
{ "id": "<uuid>", "action": "override", "created_at": "2026-04-03T12:01:00Z" }
```

If `action` is `override` or `flag`, the feedback is also pushed to the Redis `retrain_queue`.

---

### Escalations

#### `GET /escalations/pending`

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

#### `POST /doctor/retrain/trigger`

Drain the Redis retrain queue to `data/retrain_buffer.jsonl`. Requires `X-Internal-Key` header.

**Response** `200`:
```json
{ "drained": 12 }
```

---

#### `GET /health`

Same format as patient-api health response.

---

## PostCare API (port 8003)

### Care Plans

#### `POST /careplan/generate`

Generate a structured care plan from visit notes. Requires `X-Internal-Key` header (internal service call only).

**Request body**:
```json
{
  "patient_id": "<uuid>",
  "visit_notes": "Patient presents with controlled T2DM. Adjust Metformin to 1000mg BD. Follow up in 2 weeks."
}
```

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

#### `GET /careplan/{patient_id}`

Retrieve the latest care plan for a patient. Requires doctor JWT.

**Response** `200`: same shape as the create response.

---

### Follow-up Check-ins

#### `POST /followup/checkin`

Patient submits a symptom report. Urgency is assessed automatically.

**Request body**:
```json
{
  "patient_id": "<uuid>",
  "symptom_report": "I have a fever of 102°F and feel very dizzy."
}
```

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

#### `GET /escalations/pending`

Unacknowledged escalations. Requires doctor JWT. Polled by doctor portal every 60 seconds.

**Response** `200`: list of escalation objects.

---

#### `POST /escalations/{escalation_id}/acknowledge`

Mark an escalation as acknowledged. Requires doctor JWT.

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
| `401` | Missing, expired, or invalid JWT |
| `403` | Correct format but wrong role or missing `X-Internal-Key` |
| `404` | Resource not found |
| `409` | Conflict (e.g. email already registered) |
| `503` | Database or downstream dependency unavailable |

```json
{ "detail": "Human-readable error message" }
```
