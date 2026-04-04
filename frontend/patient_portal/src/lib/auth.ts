const PATIENT_API = process.env.NEXT_PUBLIC_PATIENT_API_URL || 'http://localhost:8001'

export function savePatientId(patientId: string): void {
  localStorage.setItem('patientId', patientId)
}

export function getPatientId(): string | null {
  if (typeof window === 'undefined') return null
  return localStorage.getItem('patientId')
}

export function clearAuth(): void {
  localStorage.removeItem('patientId')
}

export async function logout(): Promise<void> {
  try {
    await fetch(`${PATIENT_API}/v1/auth/logout`, {
      method: 'POST',
      credentials: 'include',
    })
  } finally {
    clearAuth()
  }
}

export function isAuthenticated(): boolean {
  return Boolean(getPatientId())
}
