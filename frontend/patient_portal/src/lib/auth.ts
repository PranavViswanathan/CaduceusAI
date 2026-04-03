export function saveToken(token: string, patientId: string): void {
  localStorage.setItem('token', token)
  localStorage.setItem('patientId', patientId)
}

export function getToken(): string | null {
  if (typeof window === 'undefined') return null
  return localStorage.getItem('token')
}

export function getPatientId(): string | null {
  if (typeof window === 'undefined') return null
  return localStorage.getItem('patientId')
}

export function clearAuth(): void {
  localStorage.removeItem('token')
  localStorage.removeItem('patientId')
}

export function isAuthenticated(): boolean {
  return Boolean(getToken())
}
