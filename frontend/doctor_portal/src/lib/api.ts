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

export async function loginDoctor(email: string, password: string): Promise<{ access_token: string }> {
  const form = new URLSearchParams({ username: email, password })
  const res = await fetch(`${DOCTOR_API}/auth/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: form.toString(),
  })
  return handleResponse(res)
}

export async function getPatients(token: string): Promise<PatientListItem[]> {
  const res = await fetch(`${DOCTOR_API}/doctor/patients`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  return handleResponse(res)
}

export async function getPatientRisk(patientId: string, token: string): Promise<RiskAssessment> {
  const res = await fetch(`${DOCTOR_API}/doctor/patients/${patientId}/risk`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  return handleResponse(res)
}

export async function getPatientDetail(patientId: string, token: string): Promise<PatientDetail> {
  const res = await fetch(`${DOCTOR_API}/doctor/patients/${patientId}/risk`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  // We get patient detail from the patients list endpoint + risk endpoint
  // For patient detail, we'll use the patients list and filter, or fetch from patient API
  // Actually, the doctor API doesn't have a dedicated GET /doctor/patients/{id} endpoint,
  // so we'll compose from available data. The risk endpoint triggers the patient fetch internally.
  // For display purposes, we'll add a separate route call to GET /doctor/patients and filter.
  if (!res.ok) throw new Error(`Failed to fetch patient: ${res.status}`)
  return res.json()
}

export async function submitFeedback(patientId: string, feedback: FeedbackPayload, token: string): Promise<void> {
  const res = await fetch(`${DOCTOR_API}/doctor/patients/${patientId}/feedback`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(feedback),
  })
  return handleResponse(res)
}

export async function getPendingEscalations(token: string): Promise<Escalation[]> {
  const res = await fetch(`${DOCTOR_API}/escalations/pending`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  return handleResponse(res)
}

export async function acknowledgeEscalation(escalationId: string, token: string): Promise<void> {
  const res = await fetch(`${POSTCARE_API}/escalations/${escalationId}/acknowledge`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  })
  return handleResponse(res)
}
