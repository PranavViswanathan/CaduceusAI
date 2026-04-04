'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { loginPatient } from '@/lib/api'
import { savePatientId } from '@/lib/auth'

export default function LoginPage() {
  const router = useRouter()
  const [step, setStep] = useState<1 | 2>(1)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [mfaCode, setMfaCode] = useState('')
  const [patientId, setPatientId] = useState('')
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [submitting, setSubmitting] = useState(false)

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault()
    const errs: Record<string, string> = {}
    if (!email.match(/^[^\s@]+@[^\s@]+\.[^\s@]+$/)) errs.email = 'Valid email required'
    if (!password) errs.password = 'Password is required'
    if (Object.keys(errs).length) { setErrors(errs); return }

    setSubmitting(true)
    setErrors({})
    try {
      const data = await loginPatient(email, password)
      setPatientId(data.patient_id)
      setStep(2)
    } catch (err) {
      setErrors({ api: err instanceof Error ? err.message : 'Invalid credentials' })
    } finally {
      setSubmitting(false)
    }
  }

  function handleMfa(e: React.FormEvent) {
    e.preventDefault()
    if (mfaCode !== '123456') {
      setErrors({ mfa: 'Invalid code. Please try again.' })
      return
    }
    savePatientId(patientId)
    router.push('/dashboard')
  }

  return (
    <main className="flex min-h-screen items-center justify-center p-8">
      <div className="w-full max-w-md">
        <div className="mb-8 text-center">
          <h1 className="text-2xl font-bold text-slate-900">Patient Portal Sign In</h1>
          <p className="text-slate-500 mt-1">
            {step === 1 ? 'Enter your credentials to continue' : 'Two-factor authentication'}
          </p>
        </div>

        <div className="mb-4 p-3 bg-amber-50 border border-amber-200 rounded-lg text-amber-800 text-sm">
          <strong>Demo credentials:</strong> patient@demo.com / demo1234
        </div>

        <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-8">
          {/* Step indicators */}
          <div className="flex items-center mb-6">
            {[1, 2].map(s => (
              <div key={s} className="flex items-center">
                <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-semibold ${step >= s ? 'bg-blue-600 text-white' : 'bg-slate-100 text-slate-400'}`}>
                  {s}
                </div>
                {s < 2 && <div className={`flex-1 h-0.5 w-16 mx-2 ${step > s ? 'bg-blue-600' : 'bg-slate-200'}`} />}
              </div>
            ))}
            <span className="ml-3 text-sm text-slate-500">
              {step === 1 ? 'Credentials' : 'Verify Identity'}
            </span>
          </div>

          {step === 1 && (
            <form onSubmit={handleLogin} className="space-y-4">
              {errors.api && (
                <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">{errors.api}</div>
              )}
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">Email Address</label>
                <input
                  type="email" value={email} onChange={e => setEmail(e.target.value)}
                  placeholder="you@example.com"
                  className={`w-full px-3 py-2.5 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${errors.email ? 'border-red-400' : 'border-slate-300'}`}
                />
                {errors.email && <p className="mt-1 text-xs text-red-600">{errors.email}</p>}
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">Password</label>
                <input
                  type="password" value={password} onChange={e => setPassword(e.target.value)}
                  className={`w-full px-3 py-2.5 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${errors.password ? 'border-red-400' : 'border-slate-300'}`}
                />
                {errors.password && <p className="mt-1 text-xs text-red-600">{errors.password}</p>}
              </div>
              <button
                type="submit" disabled={submitting}
                className="w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white font-semibold py-3 rounded-lg transition-colors"
              >
                {submitting ? 'Signing in...' : 'Continue'}
              </button>
            </form>
          )}

          {step === 2 && (
            <form onSubmit={handleMfa} className="space-y-4">
              <div className="p-3 bg-blue-50 border border-blue-200 rounded-lg text-blue-700 text-sm">
                Enter the 6-digit code from your authenticator app.
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">Authentication Code</label>
                <input
                  type="text" value={mfaCode} onChange={e => setMfaCode(e.target.value)}
                  placeholder="000000" maxLength={6}
                  className={`w-full px-3 py-2.5 border rounded-lg text-sm text-center tracking-widest text-lg font-mono focus:outline-none focus:ring-2 focus:ring-blue-500 ${errors.mfa ? 'border-red-400' : 'border-slate-300'}`}
                />
                {errors.mfa && <p className="mt-1 text-xs text-red-600">{errors.mfa}</p>}
                <p className="mt-1 text-xs text-slate-400">(Demo: use code 123456)</p>
              </div>
              <button
                type="submit"
                className="w-full bg-blue-600 hover:bg-blue-700 text-white font-semibold py-3 rounded-lg transition-colors"
              >
                Verify & Sign In
              </button>
              <button
                type="button" onClick={() => { setStep(1); setErrors({}) }}
                className="w-full text-slate-500 hover:text-slate-700 text-sm py-2"
              >
                ← Back
              </button>
            </form>
          )}
        </div>

        <p className="text-center text-slate-500 mt-6 text-sm">
          Don&apos;t have an account?{' '}
          <Link href="/register" className="text-blue-600 font-medium hover:underline">Register</Link>
        </p>
      </div>
    </main>
  )
}
