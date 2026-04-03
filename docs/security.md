# Security Model

## Authentication

### Patient Authentication (`patient-api`)

- Registration: email + bcrypt-hashed password stored in `patients` table
- Login: OAuth2 password flow (`POST /auth/token`) returns a JWT
- JWT payload: `sub = patient_id`, no role claim
- Token TTL: 30 minutes (configurable via `JWT_EXPIRE_MINUTES`)
- Algorithm: HS256 signed with `JWT_SECRET`

Protected routes use a FastAPI dependency (`get_current_patient`) that:
1. Extracts the `Authorization: Bearer <token>` header
2. Decodes and verifies the JWT signature and expiry
3. Looks up the patient in the database
4. Returns HTTP 401 if any step fails

### Doctor Authentication (`doctor-api`)

- Same flow as patient, plus a `role = "doctor"` claim in the JWT payload
- Protected routes use `get_current_doctor` which additionally asserts `role == "doctor"`
- A patient token is explicitly rejected on doctor endpoints

### Inter-Service Authentication

Service-to-service endpoints (e.g., `POST /careplan/generate`, `POST /doctor/retrain/trigger`) do not accept JWTs. They require an `X-Internal-Key` header matching `INTERNAL_API_KEY` from `.env`. Return HTTP 403 if the key is absent or wrong.

---

## PHI Encryption

### What is encrypted

| Field | Table | Method |
|---|---|---|
| `dob_encrypted` | `patients` | AES-256 via Fernet (symmetric) |

Date of birth is the only field classified as requiring encryption at rest. All other fields (name, email, phone) are stored plaintext. Passwords are hashed and never recoverable.

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
3. Update `FERNET_KEY` in `.env` and restart all services

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

Both APIs restrict cross-origin requests to the two frontend origins:

```python
allow_origins=["http://localhost:3000", "http://localhost:3001"]
allow_methods=["*"]
allow_headers=["*"]
allow_credentials=True
```

In a production deployment, replace `localhost` origins with the actual domain names.

---

## Authorization Rules

| Endpoint | Allowed |
|---|---|
| `GET /patients/{id}` | Only the authenticated patient with matching `id` |
| `GET /doctor/patients` | Any authenticated doctor |
| `GET /doctor/patients/{id}/risk` | Any authenticated doctor |
| `POST /doctor/patients/{id}/feedback` | Any authenticated doctor |
| `GET /escalations/pending` | Any authenticated doctor |
| `POST /escalations/{id}/acknowledge` | Any authenticated doctor |
| `POST /careplan/generate` | Internal key only |
| `POST /doctor/retrain/trigger` | Internal key only |

Patients cannot access any `doctor-api` or `postcare-api` routes. There is no admin role; doctor access is flat (any doctor can view any patient).

---

## Audit Logging

Every write operation across all three APIs is recorded in `audit_log`:

- **What is logged**: service, route, actor_id, patient_id, action label, outcome, IP address, timestamp
- **What is never logged**: PHI values (DOB, symptoms, medications), plaintext passwords, JWT tokens

Audit log writes are wrapped in a try/except — a logging failure must not block a legitimate clinical operation.

---

## Token Security

- JWTs use HS256 (symmetric). The `JWT_SECRET` must be a strong random string (minimum 32 characters, ideally 64+)
- Tokens expire after 30 minutes. There is no refresh token mechanism — re-authentication is required
- Tokens are stored in browser `localStorage` in both portals. For higher-security environments, consider `httpOnly` cookies

---

## Security Checklist for Production Deployment

- [ ] Replace all placeholder values in `.env` (JWT_SECRET, FERNET_KEY, INTERNAL_API_KEY, DB password)
- [ ] Set `FERNET_KEY` to a freshly generated key (never use the example key)
- [ ] Lock CORS `allow_origins` to actual production domains
- [ ] Enable HTTPS (terminate TLS at a reverse proxy, e.g. nginx + Let's Encrypt)
- [ ] Move JWT storage from `localStorage` to `httpOnly` cookies
- [ ] Add rate limiting on auth endpoints (`/auth/token`, `/auth/register`)
- [ ] Rotate `JWT_SECRET` and `INTERNAL_API_KEY` regularly
- [ ] Restrict `INTERNAL_API_KEY` endpoint access to internal network only (firewall / VPC rules)
- [ ] Enable PostgreSQL SSL (`sslmode=require` in `DATABASE_URL`)
- [ ] Audit `audit_log` table regularly; set up alerts on repeated failures
- [ ] Do not expose Ollama port (11434) outside the Docker network
