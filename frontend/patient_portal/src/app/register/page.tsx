'use client'

import { useState } from 'react'
import Link from 'next/link'
import { registerPatient } from '@/lib/api'

type FormData = {
  name: string
  email: string
  password: string
  dob: string
  sex: string
  phone: string
}

type FormErrors = Partial<FormData>

export default function RegisterPage() {
  const [form, setForm] = useState<FormData>({ name: '', email: '', password: '', dob: '', sex: '', phone: '' })
  const [errors, setErrors] = useState<FormErrors>({})
  const [submitting, setSubmitting] = useState(false)
  const [success, setSuccess] = useState(false)
  const [apiError, setApiError] = useState('')

  function validate(): boolean {
    const e: FormErrors = {}
    if (!form.name.trim()) e.name = 'Full name is required'
    if (!form.email.match(/^[^\s@]+@[^\s@]+\.[^\s@]+$/)) e.email = 'Valid email is required'
    if (form.password.length < 8) e.password = 'Password must be at least 8 characters'
    if (!form.dob) e.dob = 'Date of birth is required'
    if (!form.sex) e.sex = 'Please select your sex'
    if (!form.phone.trim()) e.phone = 'Phone number is required'
    setErrors(e)
    return Object.keys(e).length === 0
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!validate()) return
    setSubmitting(true)
    setApiError('')
    try {
      await registerPatient(form)
      setSuccess(true)
    } catch (err) {
      setApiError(err instanceof Error ? err.message : 'Registration failed')
    } finally {
      setSubmitting(false)
    }
  }

  if (success) {
    return (
      <main className="flex min-h-screen items-center justify-center p-8">
        <div className="w-full max-w-md bg-white rounded-2xl shadow-sm border border-slate-200 p-8 text-center">
          <div className="inline-flex items-center justify-center w-12 h-12 bg-green-100 rounded-full mb-4">
            <svg className="w-6 h-6 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <h2 className="text-xl font-bold text-slate-900 mb-2">Account Created</h2>
          <p className="text-slate-500 mb-6">Your account has been created successfully.</p>
          <Link href="/login" className="block w-full bg-blue-600 hover:bg-blue-700 text-white font-semibold py-3 rounded-lg transition-colors">
            Sign In
          </Link>
        </div>
      </main>
    )
  }

  return (
    <main className="flex min-h-screen items-center justify-center p-8">
      <div className="w-full max-w-lg">
        <div className="mb-8 text-center">
          <h1 className="text-2xl font-bold text-slate-900">Create Patient Account</h1>
          <p className="text-slate-500 mt-1">Register for the MedAI Patient Portal</p>
        </div>

        <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-8">
          {apiError && (
            <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">{apiError}</div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <Field label="Full Name" error={errors.name}>
              <input
                type="text" value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                placeholder="Jane Smith"
                className={input(!!errors.name)}
              />
            </Field>

            <Field label="Email Address" error={errors.email}>
              <input
                type="email" value={form.email} onChange={e => setForm(f => ({ ...f, email: e.target.value }))}
                placeholder="jane@example.com"
                className={input(!!errors.email)}
              />
            </Field>

            <Field label="Password" error={errors.password}>
              <input
                type="password" value={form.password} onChange={e => setForm(f => ({ ...f, password: e.target.value }))}
                placeholder="Minimum 8 characters"
                className={input(!!errors.password)}
              />
            </Field>

            <div className="grid grid-cols-2 gap-4">
              <Field label="Date of Birth" error={errors.dob}>
                <input
                  type="date" value={form.dob} onChange={e => setForm(f => ({ ...f, dob: e.target.value }))}
                  className={input(!!errors.dob)}
                />
              </Field>

              <Field label="Sex" error={errors.sex}>
                <select value={form.sex} onChange={e => setForm(f => ({ ...f, sex: e.target.value }))} className={input(!!errors.sex)}>
                  <option value="">Select...</option>
                  <option value="Male">Male</option>
                  <option value="Female">Female</option>
                  <option value="Other">Other</option>
                  <option value="Prefer not to say">Prefer not to say</option>
                </select>
              </Field>
            </div>

            <Field label="Phone Number" error={errors.phone}>
              <input
                type="tel" value={form.phone} onChange={e => setForm(f => ({ ...f, phone: e.target.value }))}
                placeholder="+1 (555) 000-0000"
                className={input(!!errors.phone)}
              />
            </Field>

            <button
              type="submit" disabled={submitting}
              className="w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white font-semibold py-3 rounded-lg transition-colors mt-2"
            >
              {submitting ? 'Creating account...' : 'Create Account'}
            </button>
          </form>
        </div>

        <p className="text-center text-slate-500 mt-6 text-sm">
          Already have an account?{' '}
          <Link href="/login" className="text-blue-600 font-medium hover:underline">Sign In</Link>
        </p>
      </div>
    </main>
  )
}

function Field({ label, error, children }: { label: string; error?: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-sm font-medium text-slate-700 mb-1">{label}</label>
      {children}
      {error && <p className="mt-1 text-xs text-red-600">{error}</p>}
    </div>
  )
}

function input(hasError: boolean) {
  return `w-full px-3 py-2.5 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${hasError ? 'border-red-400 bg-red-50' : 'border-slate-300'}`
}
