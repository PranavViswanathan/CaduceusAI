const DOCTOR_API = process.env.NEXT_PUBLIC_DOCTOR_API_URL || 'http://localhost:8002'
const POSTCARE_API = process.env.NEXT_PUBLIC_POSTCARE_API_URL || 'http://localhost:8003'

export type PatientListItem = {
  id: string
  name: string
  email: string
  intake_submitted_at: string | null
}

export type RiskAssessment = {
  id: string
  risks: string[]
  confidence: 'low' | 'medium' | 'high'
  summary: string
  source: 'llm' | 'rule_based'
  version: number
  created_at: string
}

export type FeedbackPayload = {
  action: 'agree' | 'override' | 'flag'
  reason?: string
  doctor_id: string
  assessment_id?: string
}

export type Escalation = {
  id: string
  patient_id: string
  patient_name: string
  urgency: string
  reason: string
  created_at: string
}

export type RetrainRunSummary = {
  version: string
  trained_at: string
  status: string
  override_rate?: number
  eval_pass_rate?: number
  items_used: number
}

export type RetrainStatus = {
  queued_count: number
  min_batch: number
  items_needed: number
  last_run: RetrainRunSummary | null
}

export type PatientDetail = {
  id: string
  name: string
  email: string
  dob: string | null
  sex: string | null
  phone: string | null
  conditions: string[]
  medications: Array<{ name: string; dose: string; frequency: string }>
  allergies: string[]
  symptoms: string | null
  intake_submitted_at: string | null
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let message = `Request failed: ${res.status}`
    try {
      const body = await res.json()
      message = body.detail || body.message || message
    } catch {}
    throw new Error(message)
  }
  return res.json() as Promise<T>
}

export async function loginDoctor(email: string, password: string): Promise<{ doctor_id: string }> {
  const form = new URLSearchParams({ username: email, password })
  const res = await fetch(`${DOCTOR_API}/v1/auth/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    credentials: 'include',
    body: form.toString(),
  })
  return handleResponse(res)
}

export async function getPatients(): Promise<PatientListItem[]> {
  const res = await fetch(`${DOCTOR_API}/v1/doctor/patients`, {
    credentials: 'include',
  })
  return handleResponse(res)
}

export async function getPatientRisk(patientId: string): Promise<RiskAssessment> {
  const res = await fetch(`${DOCTOR_API}/v1/doctor/patients/${patientId}/risk`, {
    credentials: 'include',
  })
  return handleResponse(res)
}

export async function submitFeedback(patientId: string, feedback: FeedbackPayload): Promise<void> {
  const res = await fetch(`${DOCTOR_API}/v1/doctor/patients/${patientId}/feedback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(feedback),
  })
  return handleResponse(res)
}

export async function getPendingEscalations(): Promise<Escalation[]> {
  const res = await fetch(`${DOCTOR_API}/v1/escalations/pending`, {
    credentials: 'include',
  })
  return handleResponse(res)
}

export async function getRetrainStatus(): Promise<RetrainStatus> {
  const res = await fetch(`${DOCTOR_API}/v1/doctor/retrain/status`, {
    credentials: 'include',
  })
  return handleResponse(res)
}

export async function acknowledgeEscalation(escalationId: string): Promise<void> {
  const res = await fetch(`${POSTCARE_API}/v1/escalations/${escalationId}/acknowledge`, {
    method: 'POST',
    credentials: 'include',
  })
  return handleResponse(res)
}
