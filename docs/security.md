# Security Model

## Authentication

### Patient Authentication (`patient-api`)

- Registration: email + bcrypt-hashed password stored in `patients` table
- Login: OAuth2 password flow (`POST /v1/auth/token`) issues a JWT and sets it as an httpOnly cookie named `patient_access_token`
- JWT payload: `sub = patient_id`, no role claim
- Token TTL: 30 minutes (configurable via `JWT_EXPIRE_MINUTES`)
- Algorithm: HS256 signed with `JWT_SECRET`
- Logout: `POST /v1/auth/logout` deletes the cookie server-side

Protected routes use a FastAPI dependency (`get_current_patient`) that:
1. Reads `patient_access_token` from the request cookie jar (falls back to `Authorization: Bearer` header for Swagger UI / programmatic access)
2. Decodes and verifies the JWT signature and expiry
3. Looks up the patient in the database
4. Returns HTTP 401 if any step fails

### Doctor Authentication (`doctor-api`)

- Same flow as patient; cookie name is `doctor_access_token`
- JWT payload includes `role = "doctor"`
- Protected routes use `get_current_doctor` which additionally asserts `role == "doctor"`
- A patient token is explicitly rejected on doctor endpoints

### Inter-Service Authentication

Service-to-service endpoints (e.g., `POST /v1/careplan/generate`, `POST /v1/doctor/retrain/trigger`) do not accept JWTs or cookies. They require an `X-Internal-Key` header matching `INTERNAL_API_KEY`. Return HTTP 403 if the key is absent or wrong.

---

## Cookie Security

Session JWTs are stored in **httpOnly cookies**, never in JavaScript-accessible storage. Cookie attributes:

| Attribute | Local value | Production value | Reason |
|---|---|---|---|
| `HttpOnly` | true | true | JavaScript cannot read the token (XSS protection) |
| `SameSite` | None | Strict | `None` required on localhost for cross-port sends; tighten to `Strict` once all services share one domain |
| `Secure` | true | true | Chrome requires `Secure` when `SameSite=None`; localhost is a secure context |
| `Domain` | `COOKIE_DOMAIN` (default: `localhost`) | Set `COOKIE_DOMAIN` to your domain (e.g. `api.example.com`) or blank for request-host resolution | Controls which domain receives the cookie; set via `make configure` before deploying |

---

## Rate Limiting

Auth endpoints are rate-limited using SlowAPI (keyed on client IP):

| Endpoint | Limit |
|---|---|
| `POST /v1/auth/token` | 5 requests/minute |
| `POST /v1/auth/register` | 5 requests/minute |

Exceeded limits return HTTP 429. When `TESTING=true`, limits are raised to 1000/minute.

---

## PHI Encryption

### What is encrypted

| Field | Table | Method |
|---|---|---|
| `dob_encrypted` | `patients` | AES-256 via Fernet (symmetric) |
| `query_encrypted` | `agent_escalations` | AES-256 via Fernet (symmetric) |

Date of birth and escalated agent query text are the fields classified as requiring encryption at rest. Agent queries that reach `escalation_node` may contain patient-identifying clinical language, so the raw query is encrypted before any PostgreSQL write using the same `encrypt()` function and `FERNET_KEY`. All other fields (name, email, phone) are stored plaintext. Passwords are hashed and never recoverable.

### How it works

`services/patient_api/encryption.py` (and a copy in `doctor_api`):

```python
from cryptography.fernet import Fernet

_fernet = Fernet(settings.FERNET_KEY.encode())

def encrypt(value: str) -> str:
    return _fernet.encrypt(value.encode()).decode()

def decrypt(value: str) -> str | None:
    try:
        return _fernet.decrypt(value.encode()).decode()
    except Exception:
        return None   # Silently returns None on decryption failure
```

The `FERNET_KEY` must be a URL-safe base64-encoded 32-byte key. Generate one with:

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

**Never commit the `.env` file.** The `.env.example` contains a placeholder key for reference only — it must not be used in any environment where real PHI is processed.

### Key rotation

Fernet does not support zero-downtime key rotation out of the box. To rotate:
1. Generate a new key
2. Write a migration script that decrypts all `dob_encrypted` values with the old key and re-encrypts with the new key
3. Update `FERNET_KEY` in `.env` (or Secrets Manager in AWS) and restart all services

---

## Input Validation

All API inputs are validated by Pydantic schemas before any database or LLM operations:

| Field | Constraint |
|---|---|
| `email` | Valid email format (`EmailStr`) |
| `password` | Minimum 8 characters |
| `name` | 2–100 characters |
| `dob` | `YYYY-MM-DD` format |
| `sex` | One of: `male`, `female`, `other`, `prefer_not_to_say` |
| `symptoms` / `symptom_report` | 10–5000 characters |
| `visit_notes` | 1–10000 characters |
| `action` (feedback) | One of: `agree`, `override`, `flag` |
| `reason` (feedback) | 1–2000 characters |

Validation failures return HTTP 400 with a structured Pydantic error response.

---

## Password Hashing

All passwords (patient and doctor) are hashed using **bcrypt** via `passlib`:

```python
from passlib.context import CryptContext
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

pwd_context.hash(plain_password)
pwd_context.verify(plain_password, hashed_password)
```

Plaintext passwords are never stored, logged, or returned in any API response.

---

## CORS Policy

All APIs restrict cross-origin requests to the origins listed in the `CORS_ORIGINS` environment variable (comma-separated). The default value in `.env.example` is:

```
CORS_ORIGINS=http://localhost:3000,http://localhost:3001
```

This maps to:

```python
allow_origins=settings.CORS_ORIGINS.split(",")
allow_methods=["*"]
allow_headers=["*"]
allow_credentials=True
```

`allow_credentials=True` is required for browsers to send the httpOnly session cookies on cross-origin requests.

**In production**: set `CORS_ORIGINS` to the actual frontend URLs (e.g., `https://example.com,https://doctor.example.com`). Use `make configure` to update the value interactively.

---

## Authorization Rules

| Endpoint | Allowed |
|---|---|
| `GET /v1/patients/{id}` | Only the authenticated patient with matching `id` |
| `GET /v1/doctor/patients` | Any authenticated doctor |
| `GET /v1/doctor/patients/{id}/risk` | Any authenticated doctor |
| `POST /v1/doctor/patients/{id}/feedback` | Any authenticated doctor |
| `GET /v1/escalations/pending` | Any authenticated doctor |
| `POST /v1/escalations/{id}/acknowledge` | Any authenticated doctor |
| `POST /v1/agent/query` | Any authenticated doctor |
| `GET /v1/agent/graph` | Any authenticated doctor |
| `POST /v1/careplan/generate` | Internal key only |
| `POST /v1/doctor/retrain/trigger` | Internal key only |

Patients cannot access any `doctor-api` or `postcare-api` doctor routes. There is no admin role; doctor access is flat (any doctor can view any patient).

---

## Audit Logging

Every write operation across all three APIs is recorded in `audit_log`:

- **What is logged**: service, route, actor_id, patient_id, action label, outcome, IP address, timestamp
- **What is never logged**: PHI values (DOB, symptoms, medications, query text), plaintext passwords, JWT tokens

The LangGraph agent writes one audit log entry per request at the terminal node of each execution path. Agent action labels:

| Action | Set by | Meaning |
|---|---|---|
| `agent_escalation` | `escalation_node` | Query escalated to clinician review queue |
| `agent_query_complete` | `retraining_trigger_node` | Query answered successfully; outcome field shows `query_type` or `retrain_enqueued` |

Audit log writes are wrapped in a try/except — a logging failure must not block a legitimate clinical operation.

---

## Token Security

- JWTs use HS256 (symmetric). The `JWT_SECRET` must be a strong random string (minimum 32 characters, ideally 64+)
- Tokens expire after 30 minutes. There is no refresh token mechanism — re-authentication is required
- Tokens are delivered and stored exclusively in **httpOnly cookies** — they are never accessible to JavaScript
- Only the user's ID (`patient_id` or `doctor_id`) is stored in `localStorage` for UI use

---

## AWS Security Controls

The Terraform deployment adds several layers of security beyond what is possible locally:

### Network Isolation

- All application services (ECS tasks), RDS, Redis, and the Ollama EC2 instance run in **private subnets** with no public IP addresses
- The only public-facing entry point is the ALB in the public subnets
- Security groups enforce least-privilege:
  - ALB SG: inbound 80/443 from `0.0.0.0/0` only
  - ECS tasks SG: inbound from ALB SG + self (inter-service) only
  - RDS SG: inbound 5432 from ECS tasks SG only
  - Redis SG: inbound 6379 from ECS tasks SG only
  - Ollama SG: inbound 11434 from ECS tasks SG only; SSH only if key pair is configured

### Encryption at Rest

- RDS storage: encrypted at rest (AWS KMS managed key)
- ElastiCache: encrypted at rest
- ECR images: AES-256 at rest
- EBS volumes on Ollama EC2: encrypted at rest

### Encryption in Transit

- ALB to browser: HTTPS (when `acm_certificate_arn` is provided)
- ECS tasks → RDS: enable `sslmode=require` in `DATABASE_URL` for production
- ECS tasks → Redis: set `transit_encryption_enabled = true` in `elasticache.tf` and update `REDIS_URL` to `rediss://`

### Secrets Management

- All sensitive values (`JWT_SECRET`, `FERNET_KEY`, `INTERNAL_API_KEY`, DB password) are stored in **AWS Secrets Manager** (`medical-ai/<env>/app-secrets`)
- ECS task execution role has a scoped policy to read only that specific secret ARN
- Secrets are injected into task containers at launch — they are never baked into Docker images or stored in ECR

### Ollama Instance Security

- No public IP; reachable only from within the ECS tasks security group
- AWS Systems Manager (SSM) Session Manager is enabled for admin access — no SSH key required by default
- Ollama port (11434) is not exposed through the ALB

---

## Production Hardening Checklist

### Application

- [ ] Replace all placeholder values in `.env` / Secrets Manager (`JWT_SECRET`, `FERNET_KEY`, `INTERNAL_API_KEY`, DB password)
- [ ] Set `FERNET_KEY` to a freshly generated key (never use the example key)
- [ ] Lock CORS `allow_origins` to actual production domains
- [ ] Rotate `JWT_SECRET` and `INTERNAL_API_KEY` regularly
- [x] JWT stored in `httpOnly` cookies — implemented
- [x] Rate limiting on auth endpoints (5 requests/minute per IP) — implemented
- [x] bcrypt password hashing — implemented
- [x] PHI fields (DOB, escalated queries) AES-256 encrypted at rest — implemented
- [x] Audit log on all write operations — implemented
- [ ] Consider adding a refresh token mechanism for better UX without sacrificing security
- [ ] Tighten `SameSite` cookie policy to `Strict` once all services share a single domain

### Infrastructure (AWS / Terraform)

- [x] All services in private subnets — implemented in `vpc.tf`
- [x] Security groups enforce least-privilege per tier — implemented in `security_groups.tf`
- [x] Secrets in AWS Secrets Manager — implemented in `secrets.tf`
- [x] RDS encrypted at rest — implemented in `rds.tf`
- [x] ElastiCache encrypted at rest — implemented in `elasticache.tf`
- [x] ECR scan-on-push enabled — implemented in `ecr.tf`
- [x] CloudWatch logs with 30-day retention — implemented in `iam.tf`
- [x] RDS Multi-AZ for HA — implemented in `rds.tf`
- [x] RDS deletion protection enabled — implemented in `rds.tf`
- [x] ALB access logs to S3 — implemented in `alb.tf`
- [ ] Set `acm_certificate_arn` and enable HTTPS on the ALB
- [ ] Enable `transit_encryption_enabled = true` on ElastiCache and update `REDIS_URL` to `rediss://`
- [ ] Add `sslmode=require` to `DATABASE_URL`
- [ ] Restrict Ollama SSH ingress to a specific CIDR (currently `0.0.0.0/0` when key pair is set)
- [ ] Enable AWS WAF on the ALB for OWASP top-10 protections
- [ ] Enable VPC Flow Logs for network auditing
- [ ] Set up CloudWatch alarms on 5xx error rates and target group unhealthy host counts
- [ ] Enable RDS Enhanced Monitoring and Performance Insights (Performance Insights is on by default in `rds.tf`)
- [ ] Enable AWS Config rules for compliance drift detection
- [ ] Enable AWS GuardDuty for threat detection
- [ ] Store Terraform state in an S3 backend with DynamoDB locking (commented stub in `main.tf`)
- [ ] Tag all resources with a `DataClassification` tag if handling real PHI (HIPAA BAA with AWS may be required)
