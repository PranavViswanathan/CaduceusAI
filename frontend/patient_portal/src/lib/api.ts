const PATIENT_API = process.env.NEXT_PUBLIC_PATIENT_API_URL || 'http://localhost:8001'
const POSTCARE_API = process.env.NEXT_PUBLIC_POSTCARE_API_URL || 'http://localhost:8003'

export type RegisterData = {
  email: string
  password: string
  name: string
  dob: string
  sex: string
  phone: string
}

export type MedicationItem = {
  name: string
  dose: string
  frequency: string
}

export type IntakeData = {
  conditions: string[]
  medications: MedicationItem[]
  allergies: string[]
  symptoms: string
}

export type IntakeResponse = {
  id: string
  patient_id: string
  conditions: string[]
  medications: MedicationItem[]
  allergies: string[]
  symptoms: string
  submitted_at: string
}

export type PatientData = {
  id: string
  email: string
  name: string
  dob: string | null
  sex: string | null
  phone: string | null
  created_at: string
  intake: IntakeResponse | null
}

export type CarePlanData = {
  id: string
  patient_id: string
  follow_up_date: string | null
  medications_to_monitor: string[]
  lifestyle_recommendations: string[]
  warning_signs: string[]
  visit_notes: string | null
  created_at: string
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

export async function registerPatient(data: RegisterData): Promise<{ patient_id: string }> {
  const res = await fetch(`${PATIENT_API}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  return handleResponse(res)
}

export async function loginPatient(email: string, password: string): Promise<{ access_token: string }> {
  const form = new URLSearchParams({ username: email, password })
  const res = await fetch(`${PATIENT_API}/auth/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: form.toString(),
  })
  return handleResponse(res)
}

export async function submitIntake(data: IntakeData, token: string): Promise<IntakeResponse> {
  const res = await fetch(`${PATIENT_API}/patients/intake`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(data),
  })
  return handleResponse(res)
}

export async function getPatient(patientId: string, token: string): Promise<PatientData> {
  const res = await fetch(`${PATIENT_API}/patients/${patientId}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  return handleResponse(res)
}

export async function getCarePlan(patientId: string, token: string): Promise<CarePlanData | null> {
  const res = await fetch(`${POSTCARE_API}/careplan/${patientId}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (res.status === 404) return null
  return handleResponse(res)
}
