export function saveToken(token: string, doctorId: string): void {
  localStorage.setItem('doctor_token', token)
  localStorage.setItem('doctor_id', doctorId)
}

export function getToken(): string | null {
  if (typeof window === 'undefined') return null
  return localStorage.getItem('doctor_token')
}

export function getDoctorId(): string | null {
  if (typeof window === 'undefined') return null
  return localStorage.getItem('doctor_id')
}

export function clearAuth(): void {
  localStorage.removeItem('doctor_token')
  localStorage.removeItem('doctor_id')
}

export function isAuthenticated(): boolean {
  return Boolean(getToken())
}
