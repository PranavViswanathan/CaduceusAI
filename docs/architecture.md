# System Architecture

## Overview

MedAI Platform is a three-tier, local-first medical AI system. Every tier owns a dedicated FastAPI backend and (where needed) a Next.js frontend. All tiers share a single PostgreSQL database, a Redis instance, and an Ollama LLM server.

```
┌─────────────────────────────────────────────────────────────────────┐
│  TIER 1 — Patient-Facing                                            │
│  patient-portal (Next.js :3000)  ←→  patient-api (FastAPI :8001)   │
├─────────────────────────────────────────────────────────────────────┤
│  TIER 2 — Clinical Decision Support                                 │
│  doctor-portal (Next.js :3001)   ←→  doctor-api (FastAPI :8002)    │
├─────────────────────────────────────────────────────────────────────┤
│  TIER 3 — Post-Care                                                 │
│  postcare-api (FastAPI :8003)                                       │
├─────────────────────────────────────────────────────────────────────┤
│  SHARED INFRASTRUCTURE                                              │
│  PostgreSQL :5432  |  Redis :6379  |  Ollama :11434                 │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Directory Layout

```
medical-ai-platform/
├── docker-compose.yml              # Full stack orchestration
├── .env.example                    # Configuration template
├── alembic.ini                     # Alembic configuration
├── alembic/
│   ├── env.py                      # Reads DATABASE_URL from environment
│   └── versions/
│       └── 001_initial_schema.py   # Creates all 8 tables + extensions
├── db/
│   └── init.sql                    # PostgreSQL extension bootstrap (uuid-ossp, pgcrypto)
├── services/
│   ├── patient_api/                # Tier 1 backend  (port 8001)
│   │   ├── main.py                 # Routes: /v1/auth, /v1/patients, /health
│   │   ├── models.py               # ORM: Patient, PatientIntake, AuditLog
│   │   ├── schemas.py              # Pydantic: PatientRegister, IntakeCreate, LoginResponse
│   │   ├── auth.py                 # Cookie-first JWT auth + get_current_patient dependency
│   │   ├── encryption.py           # Fernet AES-256 for PHI fields
│   │   ├── database.py             # SQLAlchemy engine + session factory
│   │   ├── settings.py             # Settings loaded from .env
│   │   ├── logging_utils.py        # Structured audit log writer
│   │   ├── requirements.txt
│   │   ├── requirements-test.txt
│   │   ├── Dockerfile
│   │   └── tests/
│   │       ├── conftest.py         # Fixtures: mock_db, authed_client, sample_patient
│   │       ├── test_auth.py        # Registration, login, logout, validation
│   │       └── test_patients.py    # Intake, profile retrieval, auth guards
│   ├── doctor_api/                 # Tier 2 backend  (port 8002)
│   │   ├── main.py                 # Routes: /v1/auth, /v1/doctor, /v1/escalations, /health
│   │   ├── models.py               # ORM: Doctor, RiskAssessment, Feedback, Escalation
│   │   ├── schemas.py              # Pydantic: DoctorRegister, FeedbackCreate, LoginResponse
│   │   ├── llm.py                  # Ollama + rule-based risk assessment
│   │   ├── auth.py                 # Cookie-first JWT auth + doctor-role guard
│   │   ├── encryption.py           # Field decryption (reads encrypted DOB)
│   │   ├── requirements.txt
│   │   ├── requirements-test.txt
│   │   ├── Dockerfile
│   │   └── tests/
│   │       ├── conftest.py
│   │       ├── test_auth.py
│   │       └── test_doctor.py      # Risk assessment, feedback, cache invalidation
│   └── postcare_api/               # Tier 3 backend  (port 8003)
│       ├── main.py                 # Routes: /v1/careplan, /v1/followup, /v1/escalations, /health
│       ├── models.py               # ORM: CarePlan, FollowupCheckin, Escalation
│       ├── schemas.py              # Pydantic: CarePlanCreate, CheckinCreate, EscalationResponse
│       ├── llm.py                  # Care plan generation + urgency assessment
│       ├── auth.py                 # Cookie-first JWT auth; get_current_user + require_doctor
│       ├── requirements.txt
│       ├── requirements-test.txt
│       ├── Dockerfile
│       └── tests/
│           ├── conftest.py         # JWT Bearer header fixtures for TestClient
│           └── test_postcare.py    # Care plans, checkins, escalation acknowledgment
├── frontend/
│   ├── patient_portal/             # Tier 1 UI  (port 3000)
│   │   └── src/app/
│   │       ├── register/page.tsx
│   │       ├── login/page.tsx
│   │       ├── intake/page.tsx     # 5-step intake wizard
│   │       ├── dashboard/page.tsx
│   │       └── lib/
│   │           ├── api.ts          # API client (credentials: 'include', /v1/ URLs)
│   │           └── auth.ts         # patient_id in localStorage; async logout()
│   └── doctor_portal/              # Tier 2 UI  (port 3001)
│       └── src/app/
│           ├── login/page.tsx
│           ├── patients/page.tsx   # Patient list + escalation alerts
│           ├── patients/[id]/page.tsx
│           └── lib/
│               ├── api.ts
│               └── auth.ts
├── scripts/
│   └── retrain_loop.py             # Feedback drain + batch processing
└── data/                           # Runtime output (created on first run)
    ├── retrain_buffer.jsonl
    └── retrain_log.jsonl
```

---

## Service Responsibilities

| Service | Port | Owns |
|---|---|---|
| `patient-api` | 8001 | Patient auth, intake storage, encrypted PHI |
| `doctor-api` | 8002 | Doctor auth, LLM risk assessment, feedback, retrain queue |
| `postcare-api` | 8003 | Care plan generation, follow-up check-ins, escalation creation |
| `patient-portal` | 3000 | Patient registration, intake wizard, care plan dashboard |
| `doctor-portal` | 3001 | Patient list, AI risk panel, feedback form, escalation alerts |
| `postgres` | 5432 | Single shared database (all tables) |
| `redis` | 6379 | Risk assessment cache, retrain queue, escalation queue |
| `ollama` | 11434 | Local LLM inference (llama3 / mistral) |
| `ollama-init` | — | One-shot: pulls llama3 + mistral into shared `ollama_data` volume |
| `migrate` | — | One-shot: runs `alembic upgrade head` before APIs start |

---

## Request Flows

### Patient Login

```
patient-portal
  → POST /v1/auth/token  (patient-api:8001)
      ├── Verify credentials
      ├── Issue JWT (HS256, 30 min TTL)
      ├── Set httpOnly cookie: patient_access_token
      └── Return { patient_id, token_type: "cookie" }

Browser stores patient_id in localStorage (not the JWT).
Subsequent requests send the cookie automatically.
```

### Patient Intake

```
patient-portal
  → POST /v1/patients/intake  (patient-api:8001)
      ├── Read patient_access_token cookie (or Bearer fallback)
      ├── Decode + verify JWT
      ├── Validate Pydantic schema (symptoms 10–5000 chars)
      ├── Write PatientIntake row
      └── Write AuditLog row
```

### Risk Assessment

```
doctor-portal
  → GET /v1/doctor/patients/{id}/risk  (doctor-api:8002)
      ├── Read doctor_access_token cookie (or Bearer fallback)
      ├── Validate JWT + assert role=doctor
      ├── Read PatientIntake from PostgreSQL
      ├── Check Redis cache (key: risk:{patient_id}, TTL 5m)
      │   ├── HIT  → return cached assessment
      │   └── MISS → call llm.get_risk_assessment()
      │               ├── Try Ollama (llama3 → mistral, 10s timeout)
      │               └── FALLBACK: rule-based drug interaction check
      ├── Write RiskAssessment row
      ├── Set Redis cache
      └── Return assessment
```

### Feedback + Cache Invalidation

```
doctor-portal
  → POST /v1/doctor/patients/{id}/feedback  (doctor-api:8002)
      ├── Write Feedback row
      ├── DELETE Redis key risk:{patient_id}   ← cache invalidated
      └── If action == override|flag:
          └── RPUSH retrain_queue  (Redis)
```

### Follow-up Check-in & Escalation

```
patient-portal (or API client)
  → POST /v1/followup/checkin  (postcare-api:8003)
      ├── Read patient_access_token or doctor_access_token cookie
      ├── Validate symptom_report (10–5000 chars)
      ├── Read latest CarePlan (warning_signs)
      ├── Call llm.assess_checkin_urgency()
      │   ├── Ollama urgency classification (routine|monitor|escalate)
      │   └── FALLBACK: keyword matching
      ├── Write FollowupCheckin row
      ├── If urgency == escalate:
      │   ├── Write Escalation row
      │   └── Push to Redis escalation_queue
      └── Return checkin + urgency

doctor-portal
  → polls GET /v1/escalations/pending  every 60s  (postcare-api:8003)
  → POST /v1/escalations/{id}/acknowledge
```

### Feedback → Retraining

```
doctor-portal
  → POST /v1/doctor/patients/{id}/feedback  (doctor-api:8002)
      ├── Write Feedback row
      └── If action == override|flag:
          └── RPUSH retrain_queue  (Redis)

(manual or scheduled)
  → POST /v1/doctor/retrain/trigger  (doctor-api:8002, requires X-Internal-Key)
      └── LPOP all items from retrain_queue
          └── Append to data/retrain_buffer.jsonl

python3 scripts/retrain_loop.py
  ├── Read retrain_buffer.jsonl
  ├── Summarise feedback events
  ├── Write to retrain_log.jsonl
  └── Clear buffer
```

---

## Docker Compose Startup Order

```
postgres  ──(healthy)──┐
                       ├──→  migrate ──(completed)──┐
redis     ──(healthy)──┘                            ├──→  patient-api
                                                    ├──→  doctor-api
                                                    └──→  postcare-api

ollama ──(healthy)──→  ollama-init  (pulls llama3 + mistral; runs once)

patient-api  ──(started)──→  patient-portal
doctor-api   ──(started)──→  doctor-portal
```

The `migrate` service runs `alembic upgrade head` once against PostgreSQL, creating all tables. API services start only after `migrate` exits successfully. The `ollama-init` service pulls required model weights on first boot; subsequent restarts skip the pull because weights are cached in the `ollama_data` Docker volume.

---

## API Versioning

All routes are registered on an `APIRouter(prefix="/v1")`. The unversioned `/health` endpoint remains accessible for liveness probes without authentication. Future breaking changes would introduce a `/v2/` router without removing `/v1/`.

---

## Rate Limiting

Auth endpoints (`/v1/auth/token`, `/v1/auth/register`) are rate-limited to **5 requests/minute per IP** using SlowAPI. When `TESTING=true`, the limit is raised to 1000/minute so tests are not throttled. All other endpoints are currently unlimited.

---

## Health Checks

Every API exposes `GET /health` returning:

```json
{ "status": "ok" }
```

or, when a dependency is degraded:

```json
{
  "status": "degraded",
  "details": {
    "postgres": "ok",
    "redis": "error: Connection refused"
  }
}
```

---

## Inter-Service Authentication

Service-to-service calls (e.g., `doctor-api` triggering a retrain drain, `postcare-api` generating a care plan) use the `X-Internal-Key` header matched against `INTERNAL_API_KEY` in `.env`. Patient and doctor session cookies are **not** accepted on internal routes.

---

## Cookie-Based Authentication

Login endpoints set an httpOnly cookie scoped to `domain=localhost` (no port). Because RFC 6265 matches cookies by host only (ignoring port), a cookie set by `:8001` is sent to `:8002` and `:8003`. Chrome treats `localhost` as a secure context, so `SameSite=None; Secure` works over plain HTTP on localhost. The JWTs are never exposed to JavaScript.

| Cookie name | Set by | Read by |
|---|---|---|
| `patient_access_token` | patient-api | patient-api, postcare-api |
| `doctor_access_token` | doctor-api | doctor-api, postcare-api |

Each auth dependency reads the cookie first; if absent, it falls back to an `Authorization: Bearer` header for Swagger UI and programmatic testing.

---

## Environment Variables

| Variable | Used By | Purpose |
|---|---|---|
| `DATABASE_URL` | all APIs, migrate | SQLAlchemy connection string |
| `REDIS_URL` | all APIs | Redis connection |
| `OLLAMA_URL` | doctor-api, postcare-api | Ollama inference endpoint |
| `JWT_SECRET` | all APIs | HMAC key for HS256 tokens |
| `FERNET_KEY` | patient-api, doctor-api | AES-256 key for PHI encryption |
| `INTERNAL_API_KEY` | doctor-api, postcare-api | Header secret for service-to-service calls |
| `JWT_ALGORITHM` | all APIs | Default: `HS256` |
| `JWT_EXPIRE_MINUTES` | all APIs | Default: `30` |
| `NEXT_PUBLIC_PATIENT_API_URL` | patient-portal | Browser-visible patient API base URL |
| `NEXT_PUBLIC_DOCTOR_API_URL` | doctor-portal | Browser-visible doctor API base URL |
| `NEXT_PUBLIC_POSTCARE_API_URL` | both portals | Browser-visible postcare API base URL |

---

## Failure Modes

| Failure | Behaviour |
|---|---|
| Ollama timeout / unavailable | Rule-based fallback (10 s timeout); response has `source: "rule_based"`, confidence `"low"` |
| PostgreSQL down | HTTP 503, no stack traces in response body |
| Redis down | Cache miss treated as no-op; queue pushes fail silently with a log warning |
| PHI decryption failure | Field returns `None`; request continues |
| Audit log write failure | DB error rolled back; request continues (logging failure ≠ auth failure) |
| Session cookie missing / expired | HTTP 401 `Not authenticated` |
| Missing `X-Internal-Key` | HTTP 403 `Forbidden` |
| Rate limit exceeded | HTTP 429 `Too Many Requests` |
