# Frontend Portals

Both portals are built with **Next.js 14** (App Router), **React 18**, **TypeScript**, and **Tailwind CSS**. They are served from separate Docker containers and communicate with their respective backend APIs over plain HTTP on `localhost` (no server-side rendering for API calls — all data fetching happens client-side).

---

## Authentication Pattern

Authentication is **cookie-based**. On login, the backend sets an httpOnly cookie (`patient_access_token` or `doctor_access_token`) that the browser sends automatically on every subsequent request. The JWT is never accessible to JavaScript.

All `fetch` calls include `credentials: 'include'` to ensure cookies are sent on cross-origin requests to the API ports. No `Authorization` headers are constructed or stored by the frontend.

The only value stored in `localStorage` is the user's ID (e.g. `patientId`, `doctorId`) for use in constructing API URLs and displaying the user's name.

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

On submit: `POST /v1/auth/register` → redirect to `/login`.

---

#### `/login` — Patient Login

Form fields:
- Email
- Password

On submit: `POST /v1/auth/token` → backend sets `patient_access_token` cookie → stores `patient_id` from response body in `localStorage` → redirects to `/intake` (first time) or `/dashboard`.

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

On submit: `POST /v1/patients/intake` → redirect to `/dashboard`.

---

#### `/dashboard` — Patient Dashboard

Three sections, loaded in parallel on mount:

1. **Profile** — `GET /v1/patients/{patient_id}`: name, email, decrypted DOB, phone
2. **Latest Intake** — rendered from profile response: conditions, medications, allergies, symptoms, submission timestamp
3. **Care Plan** — `GET /v1/careplan/{patient_id}` (postcare-api): follow-up date, medications to monitor, lifestyle recommendations, warning signs

---

### API Client (`src/lib/api.ts`)

```typescript
register(data: PatientRegisterData): Promise<Patient>
loginPatient(email: string, password: string): Promise<{ patient_id: string }>
submitIntake(data: IntakeData): Promise<IntakeResponse>
getPatient(patientId: string): Promise<PatientProfile>
getCarePlan(patientId: string): Promise<CarePlan | null>
```

All calls include `credentials: 'include'`. No token parameters — the cookie is sent automatically. Base URL is read from `process.env.NEXT_PUBLIC_PATIENT_API_URL`.

---

### Auth Helper (`src/lib/auth.ts`)

```typescript
savePatientId(patientId: string): void   // writes patient_id to localStorage
getPatientId(): string | null
clearAuth(): void                         // removes patient_id from localStorage
logout(): Promise<void>                   // calls POST /v1/auth/logout, then clearAuth()
```

`logout()` is async — it calls the backend to clear the httpOnly cookie before removing the local ID.

---

## Doctor Portal (port 3001)

### Pages

#### `/login` — Doctor Login

On success: backend sets `doctor_access_token` cookie; `doctor_id` from response body is stored in `localStorage`. Redirects to `/patients`.

---

#### `/patients` — Patient List

Displays all patients returned by `GET /v1/doctor/patients`:
- Patient name, email
- Last intake timestamp
- "View" link → `/patients/[id]`

**Escalation alert banner**: At the top of the page, a red banner appears if `GET /v1/escalations/pending` (postcare-api) returns one or more unacknowledged escalations. The banner shows the count and a link to review.

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

Loaded from `GET /v1/doctor/patients/{id}/risk`:

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

On submit: `POST /v1/doctor/patients/{id}/feedback` with `doctor_id` from `localStorage`. If `override` or `flag`, the event is queued in Redis for the retraining loop, and the patient's risk cache is invalidated.

---

### API Client (`src/lib/api.ts`)

```typescript
loginDoctor(email: string, password: string): Promise<{ doctor_id: string }>
getPatients(): Promise<Patient[]>
getPatientRisk(patientId: string): Promise<RiskAssessment>
submitFeedback(patientId: string, data: FeedbackData): Promise<void>
getPendingEscalations(): Promise<Escalation[]>
acknowledgeEscalation(escalationId: string): Promise<void>
```

All calls include `credentials: 'include'`. No token parameters.

Base URLs:
- Doctor API calls: `NEXT_PUBLIC_DOCTOR_API_URL` (default `http://localhost:8002`)
- PostCare API calls: `NEXT_PUBLIC_POSTCARE_API_URL` (default `http://localhost:8003`)

---

### Auth Helper (`src/lib/auth.ts`)

```typescript
saveDoctorId(doctorId: string): void
getDoctorId(): string | null
clearAuth(): void
logout(): Promise<void>   // calls POST /v1/auth/logout, then clearAuth()
```

---

## Shared Conventions

### No Server-Side Data Fetching

All `fetch` calls are inside `useEffect` hooks in client components (`"use client"`). There is no `getServerSideProps` or server component data fetching. This keeps the portals purely static Next.js apps that communicate with the APIs entirely from the browser.

### Error Handling

API errors are caught in `try/catch` blocks. On 401, both portals call `clearAuth()` and redirect to `/login`. Other errors display an inline error message.

### Cookie Sharing Across Ports

Because cookies are scoped to `domain=localhost` (without a port), the `patient_access_token` set by `patient-api` on `:8001` is automatically sent by the browser to `postcare-api` on `:8003`. This allows the patient portal's check-in calls to work without any additional auth steps.

### Environment Variables

| Variable | Portal | Value |
|---|---|---|
| `NEXT_PUBLIC_PATIENT_API_URL` | patient-portal | `http://localhost:8001` |
| `NEXT_PUBLIC_POSTCARE_API_URL` | both | `http://localhost:8003` |
| `NEXT_PUBLIC_DOCTOR_API_URL` | doctor-portal | `http://localhost:8002` |

These are injected at build time by Docker Compose and baked into the Next.js bundle. Changing them requires a rebuild (`docker compose up --build`).
