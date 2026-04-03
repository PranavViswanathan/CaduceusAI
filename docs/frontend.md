# Frontend Portals

Both portals are built with **Next.js 14** (App Router), **React 18**, **TypeScript**, and **Tailwind CSS**. They are served from separate Docker containers and communicate with their respective backend APIs over plain HTTP on `localhost` (no server-side rendering for API calls — all data fetching happens client-side).

---

## Patient Portal (port 3000)

### Tech Stack

| Package | Version | Purpose |
|---|---|---|
| Next.js | 14 | App Router, SSG, client components |
| React | 18 | UI framework |
| TypeScript | 5 | Static types |
| Tailwind CSS | 3 | Utility-first styling |

### Pages

#### `/` — Home

Redirects to `/login` if not authenticated, otherwise to `/dashboard`.

---

#### `/register` — Patient Registration

Form fields:
- Email
- Password
- Name
- Date of birth
- Sex (dropdown)
- Phone

On submit: `POST /auth/register` → redirect to `/login`.

---

#### `/login` — Patient Login

Form fields:
- Email
- Password

On submit: `POST /auth/token` → stores `access_token` and `patient_id` in `localStorage` → redirects to `/intake` (first time) or `/dashboard`.

---

#### `/intake` — 5-Step Intake Wizard

Each step is a separate screen within the same page component. Navigation is client-side state (no separate routes for each step).

| Step | Fields |
|---|---|
| 1 — Demographics | Review name, DOB, sex, phone (read from profile, not editable here) |
| 2 — Medical History | Add / remove condition strings |
| 3 — Medications | Add `{name, dose, frequency}` objects; remove individual entries |
| 4 — Allergies | Add / remove allergy strings |
| 5 — Symptoms | Free-text area |

On submit: `POST /patients/intake` → redirect to `/dashboard`.

---

#### `/dashboard` — Patient Dashboard

Three sections, loaded in parallel on mount:

1. **Profile** — `GET /patients/{patient_id}`: name, email, decrypted DOB, phone
2. **Latest Intake** — rendered from profile response: conditions, medications, allergies, symptoms, submission timestamp
3. **Care Plan** — `GET /careplan/{patient_id}` (postcare-api): follow-up date, medications to monitor, lifestyle recommendations, warning signs

---

### API Client (`src/app/lib/api.ts`)

```typescript
register(data: PatientRegisterData): Promise<Patient>
login(email: string, password: string): Promise<{ access_token: string }>
submitIntake(data: IntakeData, token: string): Promise<IntakeResponse>
getPatientProfile(patientId: string, token: string): Promise<PatientProfile>
getCarePlan(patientId: string, token: string): Promise<CarePlan | null>
```

All calls include `Authorization: Bearer <token>` where required. Base URL is read from `process.env.NEXT_PUBLIC_PATIENT_API_URL`.

---

### Auth Helper (`src/app/lib/auth.ts`)

```typescript
setAuth(token: string, patientId: string): void     // writes to localStorage
getToken(): string | null
getPatientId(): string | null
clearAuth(): void                                    // logout
```

---

## Doctor Portal (port 3001)

### Pages

#### `/login` — Doctor Login

Same UI pattern as patient login. On success: stores JWT and `doctor_id` in `localStorage`, redirects to `/patients`.

---

#### `/patients` — Patient List

Displays all patients returned by `GET /doctor/patients`:
- Patient name, email
- Last intake timestamp
- "View" link → `/patients/[id]`

**Escalation alert banner**: At the top of the page, a red banner appears if `GET /escalations/pending` (postcare-api) returns one or more unacknowledged escalations. The banner shows the count and a link to review.

Polling: the escalation check runs immediately on mount and repeats every **60 seconds** via `setInterval`.

---

#### `/patients/[id]` — Patient Detail + AI Risk Panel

Three sections:

**1. Patient Demographics**
- Name, email, decrypted DOB, phone, sex

**2. Latest Intake**
- Conditions (tags)
- Medications (table: name / dose / frequency)
- Allergies (tags)
- Symptoms (free text)

**3. AI Risk Assessment Panel**

Loaded from `GET /doctor/patients/{id}/risk`:

- **Risk list**: bullet points of identified clinical risks
- **Confidence badge**: colour-coded (`low` = red, `medium` = amber, `high` = green)
- **Source badge**: `LLM` or `Rule-based`
- **Summary**: clinical narrative paragraph

**Feedback Form** (below the panel):

```
○ Agree      ○ Override      ○ Flag for review

Reason (optional):
[ text area                                ]

[ Submit Feedback ]
```

On submit: `POST /doctor/patients/{id}/feedback`. If `override` or `flag`, the event is queued in Redis for the retraining loop.

---

### API Client (`src/app/lib/api.ts`)

```typescript
loginDoctor(email: string, password: string): Promise<{ access_token: string }>
getPatients(token: string): Promise<Patient[]>
getPatientProfile(patientId: string, token: string): Promise<PatientProfile>
getRiskAssessment(patientId: string, token: string): Promise<RiskAssessment>
submitFeedback(patientId: string, data: FeedbackData, token: string): Promise<void>
getPendingEscalations(token: string): Promise<Escalation[]>
acknowledgeEscalation(escalationId: string, token: string): Promise<void>
```

Base URLs:
- Doctor API calls: `NEXT_PUBLIC_DOCTOR_API_URL` (default `http://localhost:8002`)
- PostCare API calls: `NEXT_PUBLIC_POSTCARE_API_URL` (default `http://localhost:8003`)

---

### Auth Helper (`src/app/lib/auth.ts`)

```typescript
setAuth(token: string, doctorId: string): void
getToken(): string | null
getDoctorId(): string | null
clearAuth(): void
```

---

## Shared Conventions

### No Server-Side Data Fetching

All `fetch` calls are inside `useEffect` hooks in client components (`"use client"`). There is no `getServerSideProps` or server component data fetching. This keeps the portals purely static Next.js apps that communicate with the APIs entirely from the browser.

### Error Handling

API errors are caught in `try/catch` blocks. On 401, both portals call `clearAuth()` and redirect to `/login`. Other errors display an inline error message.

### Token Storage

JWTs are stored in `localStorage`. This is convenient for a local development environment but `httpOnly` cookies are recommended for any deployment where real patient data is processed.

### Environment Variables

| Variable | Portal | Value |
|---|---|---|
| `NEXT_PUBLIC_PATIENT_API_URL` | patient-portal | `http://localhost:8001` |
| `NEXT_PUBLIC_POSTCARE_API_URL` | both | `http://localhost:8003` |
| `NEXT_PUBLIC_DOCTOR_API_URL` | doctor-portal | `http://localhost:8002` |

These are injected at build time by Docker Compose and baked into the Next.js bundle. Changing them requires a rebuild (`docker compose up --build`).
