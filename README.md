# CaduceusAI Platform — Three-Tier Medical AI System

**CaduceusAI** is a local-first, three-tier medical AI platform that covers the full patient journey — from intake to clinical decision support to post-care follow-up — with all LLM inference running on-device via Ollama. No patient data ever leaves the host.

The system is split across three independently deployable tiers: a patient-facing portal for registration, intake, and care plan review; a clinical decision support layer where doctors get AI-generated risk assessments with confidence scoring and can submit feedback to correct the model; and a post-care service that generates structured care plans from visit notes and triages follow-up symptom reports into `routine`, `monitor`, or `escalate` urgency levels.

AI assessments are powered by `llama3` or `mistral` running locally, with automatic fallback to deterministic rule-based checks (drug interaction detection, keyword triage) when Ollama is unavailable or times out. Clinician disagreements — overrides and flags — are queued in Redis and drained into a retraining buffer designed to feed a LoRA fine-tuning pipeline.

The stack is fully containerized: FastAPI backends, Next.js 14 frontends, PostgreSQL, Redis, and Ollama all orchestrated via Docker Compose with automatic schema migrations (Alembic) and model pulls on first boot. Security is treated seriously — PHI is AES-256 encrypted at rest, passwords are bcrypt-hashed, JWTs live exclusively in httpOnly cookies, and every write operation is recorded in an append-only audit log.

---

## Documentation

| Doc | Description |
|---|---|
| [Architecture](docs/architecture.md) | Full system design — tiers, services, LangGraph agent, request flows, Docker orchestration, AWS deployment, failure modes |
| [AI Model & LLM](docs/model.md) | Ollama integration, LangGraph agent nodes, prompt design, rule-based fallbacks, retraining pipeline, AWS GPU inference |
| [Database Schema](docs/database.md) | All tables (incl. `agent_escalations`), columns, constraints, relationships, indexes, and AWS RDS migration |
| [API Reference](docs/api.md) | Every endpoint across all three services with request/response examples and AWS routing |
| [Frontend Portals](docs/frontend.md) | Patient and doctor portals — pages, data flows, API clients, auth helpers, AWS deployment notes |
| [Security Model](docs/security.md) | Auth, PHI encryption, CORS, audit logging, AWS security controls, and production hardening checklist |

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

For AWS deployment: [Terraform](https://developer.hashicorp.com/terraform/install) (v1.6+) and the [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html) (v2).

---

## Setup & Run (Local)

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

```bash
# Submit a clinical query to the LangGraph agent (requires doctor session cookie)
curl -X POST http://localhost:8002/v1/agent/query \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <doctor_token>" \
  -d '{"query": "What is the first-line treatment for hypertension in a diabetic patient?"}'
```

---

## AWS Deployment (Terraform)

Full infrastructure-as-code lives in the `terraform/` directory. It provisions:

- **VPC** with public + private subnets across 2 AZs
- **ALB** with path-based routing for all services
- **ECS Fargate** for all 5 application containers
- **RDS PostgreSQL 16** (Multi-AZ, encrypted)
- **ElastiCache Redis 7** (primary + replica)
- **Ollama on EC2** (`g4dn.xlarge` with NVIDIA T4 GPU)
- **ECR** repositories for all service images
- **Secrets Manager** for all sensitive values
- **CloudWatch** log groups per service

### Quick start

```bash
cd terraform

# 1. Fill in secrets and config
cp terraform.tfvars.example terraform.tfvars
# edit terraform.tfvars

# 2. Init and apply
terraform init
terraform apply

# 3. Get ECR URLs and push images
terraform output ecr_repository_urls

# 4. Run DB migrations (one-time)
aws ecs run-task \
  --cluster $(terraform output -raw ecs_cluster_name) \
  --task-definition $(terraform output -raw migrate_task_definition_arn) \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$(terraform output -json private_subnet_ids | jq -r '.[0]')],securityGroups=[$(terraform output -raw ecs_tasks_security_group_id)],assignPublicIp=DISABLED}"

# 5. Access the platform
terraform output patient_portal_url
```

See [Architecture](docs/architecture.md) for the full AWS topology.

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

```bash
python3 scripts/retrain_loop.py
```

Or from within Docker:

```bash
docker compose exec doctor-api python /app/retrain_loop.py
```

Trigger the retrain queue drain via the API:

```bash
curl -X POST http://localhost:8002/v1/doctor/retrain/trigger \
  -H "X-Internal-Key: internal-service-api-key-change-in-production"
```

See [AI Model & LLM](docs/model.md) for the full retraining pipeline.

---

## Troubleshooting

### `migrate` service exits with `DuplicateTable` error

Tables were created outside of Alembic but `alembic_version` is missing. Fix by stamping the current revision:

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
3. If the model is present but the portal still shows "AI unavailable", flush the Redis cache:
   ```bash
   docker compose exec redis redis-cli FLUSHALL
   ```
4. The first AI assessment after a cold start takes 30–90 s on CPU — this is normal.

---

## Security Notes

- All sensitive fields (DOB, escalated agent query text) are AES-256 encrypted at rest using Fernet
- Passwords are bcrypt-hashed
- JWTs use HS256, expire after 30 minutes, and are stored in **httpOnly cookies** (never in localStorage)
- Role claims (`role=doctor` vs patient) are validated on every protected route
- Inter-service calls require `X-Internal-Key` header
- Rate limiting is active on all auth endpoints (5 requests/minute per IP; 1000/minute in test mode)
- Audit log records every write operation (actor, action, outcome) without logging PHI values
- CORS is locked to `localhost:3000` and `localhost:3001` (update to real domains for production)
- In AWS: secrets live in Secrets Manager, DB is encrypted at rest (RDS), Redis is encrypted at rest (ElastiCache), Ollama is private (no public IP)

See [Security Model](docs/security.md) for the full production hardening checklist.

---

## Project Structure

```
medical-ai-platform/
├── docker-compose.yml
├── .env.example
├── alembic.ini
├── alembic/
│   ├── env.py
│   └── versions/
│       └── 001_initial_schema.py
├── db/
│   └── init.sql
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
│   │   ├── Dockerfile
│   │   └── tests/
│   ├── doctor_api/                     # Tier 2 backend (port 8002)
│   │   ├── main.py
│   │   ├── llm.py
│   │   ├── models.py
│   │   ├── langgraph.json
│   │   ├── agent/
│   │   │   ├── state.py
│   │   │   ├── models.py
│   │   │   ├── knowledge_base.py
│   │   │   ├── nodes.py
│   │   │   ├── graph.py
│   │   │   └── router.py
│   │   ├── requirements.txt
│   │   ├── Dockerfile
│   │   └── tests/
│   └── postcare_api/                   # Tier 3 backend (port 8003)
│       ├── main.py
│       ├── llm.py
│       ├── requirements.txt
│       ├── Dockerfile
│       └── tests/
├── frontend/
│   ├── patient_portal/                 # Tier 1 UI (port 3000)
│   │   └── src/app/
│   │       ├── register/page.tsx
│   │       ├── login/page.tsx
│   │       ├── intake/page.tsx
│   │       └── dashboard/page.tsx
│   └── doctor_portal/                  # Tier 2 UI (port 3001)
│       └── src/app/
│           ├── login/page.tsx
│           ├── patients/page.tsx
│           └── patients/[id]/page.tsx
├── terraform/                          # AWS infrastructure (Terraform)
│   ├── main.tf                         # Provider + backend config
│   ├── variables.tf                    # All input variables
│   ├── outputs.tf                      # ALB DNS, ECR URLs, cluster name, etc.
│   ├── vpc.tf                          # VPC, subnets, IGW, NAT, route tables
│   ├── security_groups.tf              # SGs for ALB, ECS, RDS, Redis, Ollama
│   ├── ecr.tf                          # ECR repos + lifecycle policies
│   ├── iam.tf                          # ECS execution/task roles, CloudWatch log groups
│   ├── secrets.tf                      # Secrets Manager secret
│   ├── rds.tf                          # RDS PostgreSQL 16 (Multi-AZ)
│   ├── elasticache.tf                  # ElastiCache Redis 7
│   ├── alb.tf                          # ALB, target groups, listener rules
│   ├── ecs.tf                          # ECS cluster, task definitions, services
│   ├── ollama.tf                       # EC2 g4dn.xlarge for Ollama + IAM
│   └── terraform.tfvars.example        # Variable template (copy → terraform.tfvars)
├── scripts/
│   └── retrain_loop.py
└── data/
```
