# Database Schema

All three services share a single PostgreSQL 16 database. The schema is managed with **Alembic** migrations — the `migrate` Docker Compose service runs `alembic upgrade head` automatically before any API starts. The `db/init.sql` file bootstraps the PostgreSQL extensions (`uuid-ossp`, `pgcrypto`) required before migrations run.

---

## Migrations

Alembic configuration lives at the platform root:

```
alembic.ini                     # Points to the alembic/ directory; reads DATABASE_URL from env
alembic/
├── env.py                      # Injects DATABASE_URL at runtime
└── versions/
    └── 001_initial_schema.py   # Creates all tables and indexes
```

### Running migrations — local (Docker Compose)

```bash
# Apply all pending migrations
DATABASE_URL=postgresql://user:pass@localhost:5432/medai alembic upgrade head

# Roll back the last migration
DATABASE_URL=postgresql://user:pass@localhost:5432/medai alembic downgrade -1

# Check current revision
DATABASE_URL=postgresql://user:pass@localhost:5432/medai alembic current
```

The `migrate` service handles this automatically on every `docker compose up`. To run migrations against a running stack:

```bash
docker compose run --rm migrate
```

If the tables already exist but `alembic_version` is missing (e.g. the DB was seeded outside of Alembic), stamp the current revision without re-running DDL:

```bash
docker run --rm \
  --network medical-ai-platform_default \
  --env-file .env \
  -v $(pwd)/alembic:/migrations/alembic \
  -v $(pwd)/alembic.ini:/migrations/alembic.ini \
  python:3.11-slim \
  sh -c "pip install alembic psycopg2-binary -q && cd /migrations && alembic stamp 001"
```

### Running migrations — AWS (ECS one-shot task)

In the AWS deployment, migrations are run as a one-shot ECS Fargate task using the `migrate` task definition created by Terraform. Run this after first deploy and after any schema change:

```bash
# Get values from Terraform outputs
CLUSTER=$(terraform output -raw ecs_cluster_name)
TASK_DEF=$(terraform output -raw migrate_task_definition_arn)
SUBNET=$(terraform output -json private_subnet_ids | jq -r '.[0]')
SG=$(terraform output -raw ecs_tasks_security_group_id)

aws ecs run-task \
  --cluster "$CLUSTER" \
  --task-definition "$TASK_DEF" \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNET],securityGroups=[$SG],assignPublicIp=DISABLED}"
```

Monitor the migration output in CloudWatch Logs under `/ecs/medical-ai/migrate`.

---

## Tables

### `patients`

Stores patient account credentials and demographics.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, default `uuid_generate_v4()` | |
| `email` | String | UNIQUE, NOT NULL | Login identifier |
| `hashed_password` | String | NOT NULL | bcrypt hash |
| `name` | String | NOT NULL | |
| `dob_encrypted` | String | nullable | AES-256 Fernet ciphertext |
| `sex` | String | nullable | One of: male, female, other, prefer_not_to_say |
| `phone` | String | nullable | |
| `created_at` | DateTime | default `now()` | |

**Notes**: `dob_encrypted` contains the Fernet-encrypted ISO date string. The plaintext DOB is never stored. Decryption requires `FERNET_KEY`.

---

### `patient_intake`

One row per intake submission. A patient may have many intakes; the most recent is used for risk assessment.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `patient_id` | UUID | FK `patients.id` | |
| `conditions` | JSON | nullable | Array of condition strings |
| `medications` | JSON | nullable | Array of `{name, dose, frequency}` objects |
| `allergies` | JSON | nullable | Array of allergy strings |
| `symptoms` | Text | nullable | Free-text symptom description (10–5000 chars validated at API layer) |
| `submitted_at` | DateTime | default `now()` | |

---

### `doctors`

Doctor account credentials and profile.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `email` | String | UNIQUE, NOT NULL | |
| `hashed_password` | String | NOT NULL | bcrypt hash |
| `name` | String | NOT NULL | |
| `specialty` | String | nullable | |
| `created_at` | DateTime | default `now()` | |

---

### `risk_assessments`

Every call to `GET /v1/doctor/patients/{id}/risk` that reaches the LLM or fallback creates a new row. Previous versions are retained.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | Referenced by `feedback.assessment_id` |
| `patient_id` | UUID | FK `patients.id` | |
| `version` | Integer | NOT NULL | Monotonically increasing per patient |
| `risks` | JSON | NOT NULL | Array of risk strings |
| `confidence` | String | NOT NULL | `low` / `medium` / `high` |
| `summary` | Text | NOT NULL | Clinical narrative |
| `source` | String | NOT NULL | `llm` or `rule_based` |
| `doctor_id` | UUID | FK `doctors.id`, nullable | Doctor who triggered the assessment |
| `created_at` | DateTime | default `now()` | |

The latest row per patient is also cached in Redis under `risk:{patient_id}` (TTL 300 s). Cache is invalidated when a doctor submits feedback via `POST /v1/doctor/patients/{id}/feedback`.

---

### `feedback`

Clinician response to a risk assessment. `agree` signals approval; `override` and `flag` trigger a retraining queue push.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `patient_id` | UUID | FK `patients.id` | |
| `doctor_id` | UUID | FK `doctors.id` | |
| `action` | String | NOT NULL | `agree` / `override` / `flag` |
| `reason` | Text | nullable | Doctor's free-text explanation |
| `assessment_id` | UUID | nullable | Links back to `risk_assessments.id` |
| `created_at` | DateTime | default `now()` | |

---

### `care_plans`

Generated by `postcare-api` after a clinical visit. The latest row per patient is used to provide context for urgency assessment during follow-up check-ins.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `patient_id` | UUID | FK `patients.id` | |
| `follow_up_date` | Date | nullable | Recommended follow-up date |
| `medications_to_monitor` | JSON | nullable | Array of medication name strings |
| `lifestyle_recommendations` | JSON | nullable | Array of recommendation strings |
| `warning_signs` | JSON | nullable | Array of warning sign strings; used for urgency assessment |
| `visit_notes` | Text | nullable | Raw clinician notes used as LLM input (1–10000 chars validated at API layer) |
| `created_at` | DateTime | default `now()` | |

---

### `followup_checkins`

Patient-submitted symptom reports. Each row is classified for urgency by the LLM (or fallback keyword scan).

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | Referenced by `escalations.checkin_id` |
| `patient_id` | UUID | FK `patients.id` | |
| `symptom_report` | Text | NOT NULL | Patient's free-text symptom description (10–5000 chars validated at API layer) |
| `urgency` | String | NOT NULL | `routine` / `monitor` / `escalate` |
| `reason` | Text | NOT NULL | LLM or rule-based explanation |
| `created_at` | DateTime | default `now()` | |

---

### `escalations`

Created automatically when a check-in is classified as `escalate`. Doctors acknowledge these through the portal.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `checkin_id` | UUID | FK `followup_checkins.id` | |
| `patient_id` | UUID | FK `patients.id` | Denormalised for fast queries |
| `acknowledged` | Boolean | default `false` | |
| `acknowledged_by` | UUID | nullable | Doctor UUID who acknowledged |
| `created_at` | DateTime | default `now()` | |

---

### `agent_escalations`

Created by `escalation_node` in the LangGraph agent when a query is classified as `urgent` or when `reasoning_node` returns confidence < 0.5. Kept separate from the `escalations` table (which requires a `followup_checkins` FK) so the agent layer remains decoupled from postcare workflows.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, default `uuid_generate_v4()` | |
| `patient_id` | UUID | nullable | Patient associated with the query (if provided) |
| `query_encrypted` | String | NOT NULL | Fernet/AES-256 ciphertext of the raw query text |
| `query_type` | String | NOT NULL | Triage classification that triggered escalation: `urgent` or `complex` |
| `reason` | Text | nullable | Human-readable explanation of why escalation occurred |
| `actor_id` | UUID | nullable | Doctor UUID who submitted the query |
| `acknowledged` | Boolean | default `false` | Set to `true` once a clinician has reviewed |
| `created_at` | DateTime | default `now()` | |

**Notes**: `query_encrypted` stores the query text PHI-encrypted (same Fernet key as `patients.dob_encrypted`).

---

### `doctor_patient_assignments`

Many-to-many assignment table that enforces row-level security in `doctor-api`. A doctor can only view, assess, or submit feedback for patients they are assigned to. An admin or onboarding workflow creates rows here before a doctor accesses a patient record.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, default `uuid_generate_v4()` | |
| `doctor_id` | UUID | FK `doctors.id`, NOT NULL | |
| `patient_id` | UUID | FK `patients.id`, NOT NULL | |
| `assigned_at` | DateTime | default `now()` | |
| `assigned_by` | UUID | nullable | UUID of the actor who created the assignment (defaults to the doctor themselves) |

**Constraints**: `UNIQUE(doctor_id, patient_id)` — duplicate assignments are prevented at the DB level. A re-assignment request returns the existing row (idempotent API).

**Indexes**: `ix_dpa_doctor_id` on `doctor_id`; `ix_dpa_patient_id` on `patient_id`.

---

### `audit_log`

Append-only log of all write operations. PHI values are never written here — only actor IDs, patient IDs, and action descriptions.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | BigInteger | PK, auto-increment | |
| `timestamp` | DateTime | default `now()` | |
| `service` | String | NOT NULL | `patient_api` / `doctor_api` / `postcare_api` |
| `route` | String | NOT NULL | HTTP route (e.g. `/v1/patients/intake`) |
| `actor_id` | UUID | nullable | Patient or doctor who performed the action |
| `patient_id` | UUID | nullable | Patient affected |
| `action` | String | NOT NULL | Short action label (e.g. `intake_submitted`) |
| `outcome` | String | NOT NULL | `success` / `failure` |
| `ip_address` | String | nullable | Client IP from request headers |

**Notes**: Audit log write failures are silently swallowed — an audit failure must not prevent a legitimate clinical operation from completing.

---

## Entity Relationships

```
patients ──< patient_intake
patients ──< risk_assessments >── doctors
patients ──< feedback          >── doctors
patients ──< care_plans
patients ──< followup_checkins ──< escalations
patients ──< agent_escalations >── doctors   (via patient_id / actor_id; both nullable)
patients >──< doctors  (via doctor_patient_assignments — enforces row-level security)
```

---

## Indexes

The Alembic migration creates primary key and unique constraint indexes. For production workloads, add:

```sql
-- Fast intake lookup (latest per patient)
CREATE INDEX ON patient_intake (patient_id, submitted_at DESC);

-- Fast risk assessment lookup (latest per patient)
CREATE INDEX ON risk_assessments (patient_id, created_at DESC);

-- Fast care plan lookup (latest per patient)
CREATE INDEX ON care_plans (patient_id, created_at DESC);

-- Unacknowledged escalation queries
CREATE INDEX ON escalations (acknowledged, created_at DESC);

-- Audit log queries by patient
CREATE INDEX ON audit_log (patient_id, timestamp DESC);

-- Agent escalation queries (unacknowledged, by patient)
CREATE INDEX ON agent_escalations (acknowledged, created_at DESC);
CREATE INDEX ON agent_escalations (patient_id, created_at DESC);

-- Doctor-patient assignment lookups (created by ORM; listed here for reference)
CREATE INDEX ix_dpa_doctor_id ON doctor_patient_assignments (doctor_id);
CREATE INDEX ix_dpa_patient_id ON doctor_patient_assignments (patient_id);
```

---

## PostgreSQL Extensions

Initialised by `db/init.sql` before the `migrate` service runs:

```sql
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";   -- uuid_generate_v4()
CREATE EXTENSION IF NOT EXISTS "pgcrypto";    -- gen_random_bytes() (available if needed)
```

The Alembic migration also calls these with `CREATE EXTENSION IF NOT EXISTS` as a safety guard.

In the AWS deployment (RDS), both extensions are pre-installed on PostgreSQL 16 and activated by the first `alembic upgrade head` run. No additional setup is needed in `db/init.sql` — RDS does not execute Docker `ENTRYPOINT` scripts.

---

## AWS RDS Configuration

The RDS instance created by Terraform (`terraform/rds.tf`) is configured as follows:

| Setting | Value |
|---|---|
| Engine | PostgreSQL 16.3 |
| Instance class | `db.t3.medium` (configurable via `db_instance_class` variable) |
| Storage | 50 GB gp3, auto-scales to 100 GB |
| Multi-AZ | Yes (automatic failover) |
| Encryption | At rest (AWS KMS) |
| Backups | 7-day retention, daily backup window 03:00–04:00 UTC |
| Deletion protection | Enabled (`terraform destroy` will fail unless manually disabled) |
| Final snapshot | Created on deletion (`<project>-postgres-final`) |
| Performance Insights | Enabled |

### Connecting to RDS from a local machine

RDS is in a private subnet with no public access. To run ad-hoc queries or migrations from a local machine:

```bash
# Option 1 — AWS SSM port forwarding through the Ollama EC2 (which is in the same VPC)
aws ssm start-session \
  --target $(terraform output -raw ollama_instance_id) \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters "host=$(terraform output -raw rds_endpoint),portNumber=5432,localPortNumber=5432"

# Then connect locally
psql postgresql://medical_user:<password>@localhost:5432/medical_ai

# Option 2 — run psql inside an ECS task (no EC2 required)
aws ecs run-task \
  --cluster $(terraform output -raw ecs_cluster_name) \
  --task-definition $(terraform output -raw migrate_task_definition_arn) \
  --launch-type FARGATE \
  --overrides '{"containerOverrides":[{"name":"migrate","command":["psql","$DATABASE_URL","-c","\\dt"]}]}' \
  --network-configuration "awsvpcConfiguration={subnets=[...],securityGroups=[...],assignPublicIp=DISABLED}"
```
