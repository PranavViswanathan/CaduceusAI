# MedAI Platform — Three-Tier Medical AI System

A local-first, three-tier medical AI platform using FastAPI, Next.js 14, PostgreSQL, Redis, and Ollama for local LLM inference.

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

### 2. Pull the Ollama model

Before starting all services, pull the LLM model (this can be done while the stack is running):

```bash
# Start Ollama first
docker compose up ollama -d

# Pull llama3 (recommended, ~4.7GB)
docker exec -it medical-ai-platform-ollama-1 ollama pull llama3

# Or mistral as a smaller alternative (~4.1GB)
docker exec -it medical-ai-platform-ollama-1 ollama pull mistral
```

### 3. Start the full stack

```bash
docker compose up --build
```

All services will start after PostgreSQL and Redis pass their health checks. Table creation runs automatically on each service's first startup.

### 4. Access the apps

| App | URL |
|---|---|
| Patient Portal | http://localhost:3000 |
| Doctor Dashboard | http://localhost:3001 |
| Patient API docs | http://localhost:8001/docs |
| Doctor API docs | http://localhost:8002/docs |
| PostCare API docs | http://localhost:8003/docs |

### 5. Bootstrap a doctor account

Use the API docs at http://localhost:8002/docs to register a doctor:

```bash
curl -X POST http://localhost:8001/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"doctor@hospital.com","password":"Password123","name":"Dr. Smith","specialty":"Internal Medicine"}'
```

Wait — that's the doctor API:

```bash
# Register a doctor
curl -X POST http://localhost:8002/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"doctor@hospital.com","password":"Password123","name":"Dr. Smith","specialty":"Internal Medicine"}'
```

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
curl -X POST http://localhost:8002/doctor/retrain/trigger \
  -H "X-Internal-Key: internal-service-api-key-change-in-production"
```

---

## Security Notes

- All sensitive fields (DOB) are AES-256 encrypted at rest using Fernet
- Passwords are bcrypt-hashed
- JWTs use HS256, expire after 30 minutes
- Role claims (`role=doctor` vs patient) are validated on every protected route
- Inter-service calls require `X-Internal-Key` header
- Audit log records every write operation (actor, action, outcome) without logging PHI values
- CORS is locked to `localhost:3000` and `localhost:3001`

---

## PHI Encryption

The `FERNET_KEY` in `.env` is used to encrypt sensitive patient fields before storage. **Never commit your `.env` file.** The `.env.example` contains a placeholder key for reference only.

---

## Fault Tolerance

- Every Ollama call has a 10-second timeout with automatic fallback to rule-based assessment
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
├── db/
│   └── init.sql                    # PostgreSQL extensions setup
├── services/
│   ├── patient_api/                # Tier 1 backend (port 8001)
│   │   ├── main.py
│   │   ├── models.py
│   │   ├── schemas.py
│   │   ├── auth.py
│   │   ├── encryption.py
│   │   ├── database.py
│   │   ├── settings.py
│   │   └── Dockerfile
│   ├── doctor_api/                 # Tier 2 backend (port 8002)
│   │   ├── main.py
│   │   ├── llm.py                  # Ollama + rule-based fallback
│   │   ├── models.py
│   │   └── ...
│   └── postcare_api/               # Tier 3 backend (port 8003)
│       ├── main.py
│       ├── llm.py                  # Care plan + urgency assessment
│       └── ...
├── frontend/
│   ├── patient_portal/             # Tier 1 UI (port 3000)
│   │   └── src/app/
│   │       ├── register/page.tsx
│   │       ├── login/page.tsx      # JWT auth + simulated MFA
│   │       ├── intake/page.tsx     # 5-step intake form
│   │       └── dashboard/page.tsx
│   └── doctor_portal/              # Tier 2 UI (port 3001)
│       └── src/app/
│           ├── login/page.tsx
│           ├── patients/page.tsx
│           └── patients/[id]/page.tsx  # LLM risk panel + feedback
├── scripts/
│   └── retrain_loop.py             # Feedback → retraining pipeline intake
└── data/                           # Runtime data (retrain_buffer.jsonl, logs)
```
