const DOCTOR_API = process.env.NEXT_PUBLIC_DOCTOR_API_URL || 'http://localhost:8002'

export function saveDoctorId(doctorId: string): void {
  localStorage.setItem('doctor_id', doctorId)
}

export function getDoctorId(): string | null {
  if (typeof window === 'undefined') return null
  return localStorage.getItem('doctor_id')
}

export function clearAuth(): void {
  localStorage.removeItem('doctor_id')
}

export async function logout(): Promise<void> {
  try {
    await fetch(`${DOCTOR_API}/v1/auth/logout`, {
      method: 'POST',
      credentials: 'include',
    })
  } finally {
    clearAuth()
  }
}

export function isAuthenticated(): boolean {
  return Boolean(getDoctorId())
}
