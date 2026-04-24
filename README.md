# CaduceusAI Platform — Three-Tier Medical AI System

**CaduceusAI** is a local-first, three-tier medical AI platform built on FastAPI, Next.js 14, PostgreSQL, Redis, and Ollama. All LLM inference runs on-device — no patient data leaves the host or the VPC in the AWS deployment.

The clinical decision support tier (Tier 2) is built around a **LangGraph `StateGraph`** that routes each query through a five-node pipeline: a triage node classifies queries as `routine`, `complex`, or `urgent` via Ollama; the RAG node retrieves the top-3 semantically similar documents from a **ChromaDB** collection (cosine similarity over `all-MiniLM-L6-v2` embeddings) and grounds Ollama's response in that context; a chain-of-thought reasoning node handles complex queries with confidence scoring; an escalation node PHI-encrypts low-confidence or urgent queries into PostgreSQL; and a retraining trigger node pushes low-scored responses to a Redis queue for model improvement. Risk assessments use a model priority cascade — `medical-risk-ft` (fine-tuned) → `llama3` → `mistral` → deterministic rule-based fallback — with results cached in Redis at a 300 s TTL.

Clinician feedback (`override` / `flag`) drains from Redis into a JSONL buffer, which feeds an automated **PEFT LoRA fine-tuning pipeline**: `TinyLlama-1.1B-Chat` is fine-tuned on Alpaca-formatted examples, the adapter is merged and converted to GGUF via `llama.cpp`, and the resulting `medical-risk-ft` model is registered back into Ollama — making it the new first-choice inference target on the next request.

The stack runs as a Docker Compose application with dependency-ordered startup, Alembic-managed schema migrations, and automatic model pulls. PHI fields are Fernet-encrypted (AES-256-CBC) at rest, passwords are bcrypt-hashed, JWTs are HS256-signed and stored exclusively in `httpOnly` cookies, and every write operation produces an append-only audit log row. For production, a Terraform module provisions the full topology on AWS: ECS Fargate for all five application services, RDS PostgreSQL 16 (Multi-AZ), ElastiCache Redis 7, and an EC2 `g4dn.xlarge` running Ollama with an NVIDIA T4 GPU (~2–5 s inference vs. 30–90 s on CPU).

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
├─────────────────────────────────────────────────────────────┤
│  ML INFRASTRUCTURE                                          │
│  MLflow :5001 (experiment tracking + model registry)        │
├─────────────────────────────────────────────────────────────┤
│  OBSERVABILITY                                              │
│  OTel Collector :4318 | Prometheus :9090                    │
│  Grafana :3030          | Jaeger :16686                     │
└─────────────────────────────────────────────────────────────┘
```

---
## Screenshots
<img width="1725" height="942" alt="image" src="https://github.com/user-attachments/assets/986c24d5-1c06-40b2-a9ad-9013302f1db0" />

<img width="1303" height="724" alt="image" src="https://github.com/user-attachments/assets/0c37e2b6-5c95-490b-94af-1494132fb465" />

<img width="980" height="877" alt="image" src="https://github.com/user-attachments/assets/96f124ab-538f-483a-8c71-13ddc1c56567" />

<img width="1501" height="948" alt="image" src="https://github.com/user-attachments/assets/ef72b452-5ec5-485e-9107-2e3e14645a2d" />


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
| `ollama` | 11434 | Local LLM inference (llama3 / mistral / medical-risk-ft) |
| `ollama-init` | — | One-shot service that pulls llama3 + mistral on first boot |
| `migrate` | — | One-shot service that runs Alembic migrations before APIs start |
| `retrain-worker` | — | Continuous PEFT LoRA training loop; registers fine-tuned model with Ollama; logs runs to MLflow |
| `mlflow` | 5001 | MLflow tracking server — experiment logs, metrics, artifacts, and model registry for fine-tuned models |
| `otel-collector` | 4317/4318 | Receives OTLP spans + metrics from all APIs; converts traces → metrics via spanmetrics connector |
| `prometheus` | 9090 | Scrapes metrics endpoint from OTel Collector every 15 s |
| `grafana` | 3030 | Pre-provisioned dashboards over Prometheus metrics and Jaeger traces (admin / admin) |
| `jaeger` | 16686 | Distributed trace storage and query UI |

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

To set or update `CORS_ORIGINS` and `COOKIE_DOMAIN` interactively:

```bash
make configure
```

This creates `.env` from `.env.example` if it does not exist, then prompts for the two values (blank input keeps the current value). Run before `make start` when deploying to a custom domain.

### 2. Start the full stack

```bash
make start
```

This builds images, starts all services in detached mode, and waits for the three API health endpoints to respond before printing the access URLs. Run `make` with no arguments to see all available targets.

Docker Compose handles the complete startup sequence automatically:

1. **postgres** and **redis** start and pass health checks
2. **migrate** runs `alembic upgrade head` to apply all schema migrations
3. **ollama** starts; **ollama-init** pulls `llama3` and `mistral` (~4.7 GB + ~4.1 GB on first run — this may take several minutes). If `ollama-init` is slow or fails, models can be pulled manually (see Troubleshooting below).
4. **mlflow** starts and passes its health check (SQLite backend, exposes UI on `:5001`)
5. All three API services start once `migrate` completes
6. Both frontend portals start
7. **retrain-worker** starts and begins polling for feedback data (depends on postgres, redis, ollama, and mlflow being healthy)

Model weights are stored in Docker volumes (`ollama_data`, `hf_cache`, `model_artifacts`) and are only downloaded/trained once. The first LoRA training run also downloads the `TinyLlama-1.1B` base model from HuggingFace (~2.2 GB).

**Other useful commands:**

```bash
make health   # check container status and API health endpoints
make stop     # stop all services (volumes preserved)
docker compose down -v  # stop and delete all data volumes
```

### 3. Access the apps

| App | URL |
|---|---|
| Patient Portal | http://localhost:3000 |
| Doctor Dashboard | http://localhost:3001 |
| Patient API docs | http://localhost:8001/docs |
| Doctor API docs | http://localhost:8002/docs |
| PostCare API docs | http://localhost:8003/docs |
| Grafana dashboards | http://localhost:3030 (admin / admin) |
| Prometheus | http://localhost:9090 |
| Jaeger traces | http://localhost:16686 |
| MLflow UI | http://localhost:5001 |

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

## Observability

All three API services are instrumented with **OpenTelemetry**. Every request, database query, Redis operation, and Ollama inference call generates a trace and contributes to Prometheus metrics. No code changes are needed to start collecting telemetry — instrumentation activates automatically on startup.

### What is traced

| Signal | Source | Span name |
|---|---|---|
| HTTP requests | FastAPI auto-instrumentation | `GET /health`, `POST /v1/auth/token`, … |
| PostgreSQL queries | SQLAlchemy auto-instrumentation | `SELECT`, `INSERT`, `UPDATE` |
| Redis commands | Redis auto-instrumentation | `GET`, `SET`, `LPUSH`, `SETEX` |
| Ollama HTTP calls | HTTPX auto-instrumentation | `HTTP POST` |
| Ollama risk assessment | Manual span (`doctor_api/llm.py`) | `ollama.risk_assessment` |
| Ollama care plan | Manual span (`postcare_api/llm.py`) | `ollama.care_plan` |
| Ollama urgency | Manual span (`postcare_api/llm.py`) | `ollama.urgency_assessment` |
| Agent triage | Manual span (`agent/nodes.py`) | `agent.triage` |
| Agent RAG | Manual span (`agent/nodes.py`) | `agent.rag` |
| Agent reasoning | Manual span (`agent/nodes.py`) | `agent.reasoning` |
| Agent escalation | Manual span (`agent/nodes.py`) | `agent.escalation` |
| Agent retrain trigger | Manual span (`agent/nodes.py`) | `agent.retraining_trigger` |

### Prometheus metrics (via spanmetrics connector)

The OTel Collector's `spanmetrics` connector converts every span into two Prometheus metrics:

- `medical_ai_traces_spanmetrics_calls_total` — request rate by `span_name`, `service_name`, `status_code`
- `medical_ai_traces_spanmetrics_duration_milliseconds_*` — latency histograms with the same labels

Custom histograms and counters exported directly from the SDK:

| Metric | Type | Labels |
|---|---|---|
| `medical_ai_ollama_request_duration_seconds` | Histogram | `ollama_model`, `ollama_operation`, `service_name` |
| `medical_ai_ollama_fallback_total` | Counter | `ollama_operation`, `service_name` |
| `medical_ai_agent_node_duration_seconds` | Histogram | `agent_node` |

### Grafana dashboard

Open **http://localhost:3030** (admin / admin). The pre-provisioned **Medical AI Platform** dashboard contains nine panels:

1. HTTP request rate by service
2. HTTP p50 / p95 latency by service
3. Ollama inference duration (p50 / p95) by operation
4. Ollama fallback rate (how often rule-based fallback fires)
5. DB query rate (SELECT / INSERT / UPDATE / DELETE)
6. DB query p95 latency
7. Redis operation rate
8. Agent node p95 duration (bargauge by node name)
9. Agent node call rate over time

Traces are browsable in **Jaeger** at http://localhost:16686 — search by service name (`patient_api`, `doctor_api`, `postcare_api`) to see end-to-end request traces.

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

## LoRA Retraining

The `retrain-worker` service runs a continuous polling loop that automatically fine-tunes the risk assessment model from clinician feedback.

**How it works:**

1. Doctors submit feedback (`override` or `flag`) via the doctor portal
2. Feedback is queued in Redis (`retrain_queue`)
3. Drain the queue into the buffer:
   ```bash
   curl -X POST http://localhost:8002/v1/doctor/retrain/trigger \
     -H "X-Internal-Key: <INTERNAL_API_KEY>"
   ```
4. `retrain-worker` polls the buffer every 5 minutes. Once `MIN_RETRAIN_BATCH` items accumulate (default 5), it:
   - Fetches original assessment context from PostgreSQL
   - Builds an Alpaca-format training dataset
   - Fine-tunes `TinyLlama-1.1B` with PEFT LoRA (CPU, ~2 epochs)
   - Merges the adapter and converts to GGUF via llama.cpp
   - Registers `medical-risk-ft:latest` with Ollama
   - Logs the run to MLflow (params, metrics, artifacts) and transitions the registered model to `Production` in the MLflow model registry
5. `doctor-api` automatically prefers `medical-risk-ft` over `llama3` / `mistral` once it is registered

**Check training status:**

```bash
curl http://localhost:8002/v1/doctor/retrain/status \
  -H "Authorization: Bearer <token>"
```

**Run manually:**

```bash
python3 scripts/retrain_loop.py
```

See [AI Model & LLM](docs/model.md) for full pipeline details, hyperparameter reference, and configuration options.

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
- CORS allowed origins are configured via `CORS_ORIGINS` in `.env` (comma-separated list; defaults to `http://localhost:3000,http://localhost:3001`). Use `make configure` to update interactively.
- Cookie domain is controlled by `COOKIE_DOMAIN` in `.env` (defaults to `localhost`; set to your domain or leave blank for production)
- In AWS: secrets live in Secrets Manager, DB is encrypted at rest (RDS), Redis is encrypted at rest (ElastiCache), Ollama is private (no public IP)

See [Security Model](docs/security.md) for the full production hardening checklist.

---

## Project Structure

```
medical-ai-platform/
├── Makefile                            # start / stop / health targets
├── docker-compose.yml
├── otel-collector-config.yaml          # OTel Collector: OTLP receiver, spanmetrics, Prometheus + Jaeger exporters
├── prometheus.yml                      # Prometheus scrape config (scrapes otel-collector:8889)
├── grafana/
│   ├── provisioning/
│   │   ├── datasources/datasources.yml # Auto-provision Prometheus + Jaeger datasources
│   │   └── dashboards/dashboards.yml   # Dashboard file provider config
│   └── dashboards/
│       └── medical-ai.json             # 9-panel Medical AI Platform dashboard
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
│   │   ├── telemetry.py                # OTel SDK setup (TracerProvider, MeterProvider, auto-instrumentation)
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
│   │   ├── telemetry.py                # OTel SDK setup
│   │   ├── llm.py                      # Ollama calls — manual spans + ollama.request.duration histogram
│   │   ├── models.py
│   │   ├── langgraph.json
│   │   ├── agent/
│   │   │   ├── state.py
│   │   │   ├── models.py
│   │   │   ├── knowledge_base.py
│   │   │   ├── nodes.py               # Per-node spans + agent.node.duration histogram
│   │   │   ├── graph.py
│   │   │   └── router.py
│   │   ├── requirements.txt
│   │   ├── Dockerfile
│   │   └── tests/
│   └── postcare_api/                   # Tier 3 backend (port 8003)
│       ├── main.py
│       ├── telemetry.py                # OTel SDK setup
│       ├── llm.py                      # Ollama calls — manual spans + metrics
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
│           ├── patients/[id]/page.tsx
│           ├── escalations/page.tsx    # Agent escalation queue
│           └── agent/page.tsx          # LangGraph clinical agent chat
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
