# CaduceusAI Platform — Three-Tier Medical AI System

**CaduceusAI** is a local-first, three-tier medical AI platform that covers the full patient journey — from intake to clinical decision support to post-care follow-up  with all LLM inference running on-device via Ollama. No patient data ever leaves the host.

The system is split across three independently deployable tiers: a patient-facing portal for registration, intake, and care plan review; a clinical decision support layer where doctors get AI-generated risk assessments with confidence scoring and can submit feedback to correct the model; and a post-care service that generates structured care plans from visit notes and triages follow-up symptom reports into `routine`, `monitor`, or `escalate` urgency levels.

AI assessments are powered by `llama3` or `mistral` running locally, with automatic fallback to deterministic rule-based checks (drug interaction detection, keyword triage) when Ollama is unavailable or times out. Clinician disagreements — overrides and flags — are queued in Redis and drained into a retraining buffer designed to feed a LoRA fine-tuning pipeline.

The stack is fully containerized: FastAPI backends, Next.js 14 frontends, PostgreSQL, Redis, and Ollama all orchestrated via Docker Compose with automatic schema migrations (Alembic) and model pulls on first boot. Security is treated seriously — PHI is AES-256 encrypted at rest, passwords are bcrypt-hashed, JWTs live exclusively in httpOnly cookies, and every write operation is recorded in an append-only audit log.

---

## Documentation

| Doc | Description |
|---|---|
| [Architecture](docs/architecture.md) | Full system design — tiers, services, request flows, Docker orchestration, failure modes |
| [AI Model & LLM](docs/model.md) | Ollama integration, prompt design, rule-based fallbacks, retraining pipeline, assessment versioning |
| [Database Schema](docs/database.md) | All tables, columns, constraints, relationships, and recommended indexes |
| [API Reference](docs/api.md) | Every endpoint across all three services with request/response examples |
| [Frontend Portals](docs/frontend.md) | Patient and doctor portals — pages, data flows, API clients, auth helpers |
| [Security Model](docs/security.md) | Auth, PHI encryption, CORS, audit logging, and production hardening checklist |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  TIER 1 — Patient-Facing                                    │
│  patient-portal (Next.js :3000) ←→ patient-api (FastAPI :8001) │
├─────────────────────────────────────────────────────────────┤
│  TIER 2 — Clinical Decision Support                         │
│  doctor-portal (Next.js :3001) ←→ doctor-api (FastAPI :8002)  │
├─────────────────────────────────────────────────────────────┤
│  TIER 3 — Post-Care                                         │
│  postcare-api (FastAPI :8003)                               │
├─────────────────────────────────────────────────────────────┤
│  SHARED INFRASTRUCTURE                                      │
│  PostgreSQL :5432 | Redis :6379 | Ollama :11434             │
└─────────────────────────────────────────────────────────────┘
```

---

## Services

| Service | Port | Description |
|---|---|---|
| `patient-portal` | 3000 | Patient-facing web app (registration, intake, dashboard) |
| `patient-api` | 8001 | Patient auth, intake submission, encrypted record storage |
| `doctor-portal` | 3001 | Clinical dashboard with AI risk panel and feedback |
| `doctor-api` | 8002 | Doctor auth, LLM risk assessment, feedback collection |
| `postcare-api` | 8003 | Care plan generation, follow-up check-ins, escalations |
| `postgres` | 5432 | Primary database (shared by all services) |
| `redis` | 6379 | Cache, retrain queue, escalation queue |
| `ollama` | 11434 | Local LLM inference (llama3 / mistral) |
| `ollama-init` | — | One-shot service that pulls llama3 + mistral on first boot |
| `migrate` | — | One-shot service that runs Alembic migrations before APIs start |

---

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (v24+)
- [Docker Compose](https://docs.docker.com/compose/) (v2.20+)

---

## Setup & Run

### 1. Configure environment

```bash
cp .env.example .env
```

Generate a proper Fernet key (required for PHI encryption):

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Paste the output as the value of `FERNET_KEY` in `.env`. Also change `JWT_SECRET` and `INTERNAL_API_KEY` to strong random values.

### 2. Start the full stack

```bash
docker compose up --build
```

Docker Compose handles the complete startup sequence automatically:

1. **postgres** and **redis** start and pass health checks
2. **migrate** runs `alembic upgrade head` to apply all schema migrations
3. **ollama** starts; **ollama-init** pulls `llama3` and `mistral` (~4.7 GB + ~4.1 GB on first run — this may take several minutes). If `ollama-init` is slow or fails, models can be pulled manually (see Troubleshooting below).
4. All three API services start once `migrate` completes
5. Both frontend portals start

Model weights are stored in a Docker volume (`ollama_data`) and only downloaded on first boot.

### 3. Access the apps

| App | URL |
|---|---|
| Patient Portal | http://localhost:3000 |
| Doctor Dashboard | http://localhost:3001 |
| Patient API docs | http://localhost:8001/docs |
| Doctor API docs | http://localhost:8002/docs |
| PostCare API docs | http://localhost:8003/docs |

### 4. Bootstrap a doctor account

Use the API docs at http://localhost:8002/docs or curl:

```bash
# Register a doctor
curl -X POST http://localhost:8002/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"doctor@hospital.com","password":"Password123","name":"Dr. Smith","specialty":"Internal Medicine"}'

# Register a patient
curl -X POST http://localhost:8001/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"patient@example.com","password":"Password123","name":"Jane Doe","dob":"1990-05-14","sex":"female"}'
```

---

## Running Tests

Each service has its own test suite using pytest. Tests run against a mock database and do not require Docker.

```bash
# Patient API tests
cd services/patient_api
pip install -r requirements.txt -r requirements-test.txt
TESTING=true pytest tests/ -v

# Doctor API tests
cd services/doctor_api
pip install -r requirements.txt -r requirements-test.txt
TESTING=true pytest tests/ -v

# PostCare API tests
cd services/postcare_api
pip install -r requirements.txt -r requirements-test.txt
TESTING=true pytest tests/ -v
```

The `TESTING=true` environment variable skips database `create_all()` on startup and sets a relaxed rate limit (1000/minute) so tests are not throttled.

---

## Retrain Loop Script

The retrain loop script processes clinician feedback that was flagged for model improvement.

### Run it

```bash
# From the repo root
python3 scripts/retrain_loop.py
```

Or from within Docker:

```bash
docker compose exec doctor-api python /app/retrain_loop.py
```

### What it does

1. Reads `./data/retrain_buffer.jsonl` (populated when doctors override or flag AI assessments)
2. Prints a summary of each feedback item: patient_id, action, reason, and assessment used
3. Appends a timestamped processing record to `./data/retrain_log.jsonl`
4. Clears the buffer

In a production system, this step would feed into a LoRA fine-tuning pipeline — see the comment block at the top of `scripts/retrain_loop.py` for the full architecture description.

### Trigger the retrain queue drain (API)

The doctor-api also exposes an internal endpoint to drain the Redis queue to the JSONL file:

```bash
curl -X POST http://localhost:8002/v1/doctor/retrain/trigger \
  -H "X-Internal-Key: internal-service-api-key-change-in-production"
```

---

## Troubleshooting

### `migrate` service exits with `DuplicateTable` error

This happens if tables were created outside of Alembic (e.g. by a previous stack that didn't complete cleanly) but the `alembic_version` table is missing. Fix by stamping the current revision:

```bash
docker run --rm \
  --network medical-ai-platform_default \
  --env-file .env \
  -v $(pwd)/alembic:/migrations/alembic \
  -v $(pwd)/alembic.ini:/migrations/alembic.ini \
  python:3.11-slim \
  sh -c "pip install alembic psycopg2-binary -q && cd /migrations && alembic stamp 001"
```

Then restart:

```bash
docker compose up -d patient-api doctor-api postcare-api
```

### Ollama healthcheck fails (`curl: not found`)

The `ollama/ollama` image does not include `curl`. The healthcheck uses `ollama list` instead — this is already set correctly in `docker-compose.yml`.

### AI unavailable / rule-based fallback shown

1. Confirm llama3 is pulled: `curl http://localhost:11434/api/tags`
2. If the model list is empty, pull manually:
   ```bash
   docker compose exec ollama ollama pull llama3
   ```
3. If the model is present but the portal still shows "AI unavailable", flush the Redis cache (a stale rule-based result may be cached):
   ```bash
   docker compose exec redis redis-cli FLUSHALL
   ```
4. The first AI assessment after a cold start takes 30–90 s on CPU — this is normal.

---

## Security Notes

- All sensitive fields (DOB) are AES-256 encrypted at rest using Fernet
- Passwords are bcrypt-hashed
- JWTs use HS256, expire after 30 minutes, and are stored in **httpOnly cookies** (never in localStorage)
- Auth cookies are set with `SameSite=None; Secure; HttpOnly; Domain=localhost`, allowing them to be shared across the three API ports on localhost
- Role claims (`role=doctor` vs patient) are validated on every protected route
- Inter-service calls require `X-Internal-Key` header
- Rate limiting is active on all auth endpoints (5 requests/minute per IP; 1000/minute in test mode)
- Audit log records every write operation (actor, action, outcome) without logging PHI values
- CORS is locked to `localhost:3000` and `localhost:3001`

---

## PHI Encryption

The `FERNET_KEY` in `.env` is used to encrypt sensitive patient fields before storage. **Never commit your `.env` file.** The `.env.example` contains a placeholder key for reference only.

---

## Fault Tolerance

- Every Ollama call has a 120-second timeout with automatic fallback to rule-based assessment (CPU inference of llama3 can take 30–90 s)
- Redis failures are silent (cache miss, no caching)
- PostgreSQL failures return HTTP 503 with a safe error message (no stack traces)
- Each service exposes `GET /health` reporting DB + Redis status

---

## Development

To run a single service locally (outside Docker):

```bash
cd services/patient_api
pip install -r requirements.txt
DATABASE_URL=postgresql://... JWT_SECRET=... FERNET_KEY=... uvicorn main:app --port 8001 --reload
```

---

## Project Structure

```
medical-ai-platform/
├── docker-compose.yml
├── .env.example
├── alembic.ini                         # Alembic configuration
├── alembic/
│   ├── env.py                          # Alembic environment (reads DATABASE_URL)
│   └── versions/
│       └── 001_initial_schema.py       # Initial schema migration
├── db/
│   └── init.sql                        # PostgreSQL extensions bootstrap
├── services/
│   ├── patient_api/                    # Tier 1 backend (port 8001)
│   │   ├── main.py
│   │   ├── models.py
│   │   ├── schemas.py
│   │   ├── auth.py
│   │   ├── encryption.py
│   │   ├── database.py
│   │   ├── settings.py
│   │   ├── requirements.txt
│   │   ├── requirements-test.txt
│   │   ├── Dockerfile
│   │   └── tests/
│   │       ├── conftest.py
│   │       ├── test_auth.py
│   │       └── test_patients.py
│   ├── doctor_api/                     # Tier 2 backend (port 8002)
│   │   ├── main.py
│   │   ├── llm.py                      # Ollama + rule-based fallback
│   │   ├── models.py
│   │   ├── requirements.txt
│   │   ├── requirements-test.txt
│   │   └── tests/
│   │       ├── conftest.py
│   │       ├── test_auth.py
│   │       └── test_doctor.py
│   └── postcare_api/                   # Tier 3 backend (port 8003)
│       ├── main.py
│       ├── llm.py                      # Care plan + urgency assessment
│       ├── requirements.txt
│       ├── requirements-test.txt
│       └── tests/
│           ├── conftest.py
│           └── test_postcare.py
├── frontend/
│   ├── patient_portal/                 # Tier 1 UI (port 3000)
│   │   └── src/app/
│   │       ├── register/page.tsx
│   │       ├── login/page.tsx
│   │       ├── intake/page.tsx         # 5-step intake form
│   │       └── dashboard/page.tsx
│   └── doctor_portal/                  # Tier 2 UI (port 3001)
│       └── src/app/
│           ├── login/page.tsx
│           ├── patients/page.tsx
│           └── patients/[id]/page.tsx  # LLM risk panel + feedback
├── scripts/
│   └── retrain_loop.py                 # Feedback → retraining pipeline intake
└── data/                               # Runtime data (retrain_buffer.jsonl, logs)
```
