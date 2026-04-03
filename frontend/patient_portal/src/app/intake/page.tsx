'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { submitIntake, MedicationItem } from '@/lib/api'
import { getToken, getPatientId } from '@/lib/auth'

type FormState = {
  conditions: string[]
  medications: MedicationItem[]
  allergies: string[]
  symptoms: string
}

const STEP_LABELS = ['Demographics', 'Medical History', 'Medications', 'Allergies', 'Symptoms']

export default function IntakePage() {
  const router = useRouter()
  const [step, setStep] = useState(1)
  const [form, setForm] = useState<FormState>({ conditions: [], medications: [], allergies: [], symptoms: '' })
  const [conditionInput, setConditionInput] = useState('')
  const [allergyInput, setAllergyInput] = useState('')
  const [medInputs, setMedInputs] = useState({ name: '', dose: '', frequency: '' })
  const [stepError, setStepError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [apiError, setApiError] = useState('')

  useEffect(() => {
    if (!getToken()) router.replace('/login')
  }, [router])

  function addCondition() {
    const val = conditionInput.trim()
    if (val && !form.conditions.includes(val)) {
      setForm(f => ({ ...f, conditions: [...f.conditions, val] }))
      setConditionInput('')
    }
  }

  function removeCondition(c: string) {
    setForm(f => ({ ...f, conditions: f.conditions.filter(x => x !== c) }))
  }

  function addAllergy() {
    const val = allergyInput.trim()
    if (val && !form.allergies.includes(val)) {
      setForm(f => ({ ...f, allergies: [...f.allergies, val] }))
      setAllergyInput('')
    }
  }

  function removeAllergy(a: string) {
    setForm(f => ({ ...f, allergies: f.allergies.filter(x => x !== a) }))
  }

  function addMedication() {
    if (!medInputs.name.trim() || !medInputs.dose.trim() || !medInputs.frequency.trim()) {
      setStepError('Please fill in all medication fields')
      return
    }
    setForm(f => ({ ...f, medications: [...f.medications, { ...medInputs }] }))
    setMedInputs({ name: '', dose: '', frequency: '' })
    setStepError('')
  }

  function removeMedication(i: number) {
    setForm(f => ({ ...f, medications: f.medications.filter((_, idx) => idx !== i) }))
  }

  function validateStep(): boolean {
    setStepError('')
    if (step === 5 && form.symptoms.trim().length < 10) {
      setStepError('Please describe your symptoms in at least 10 characters')
      return false
    }
    return true
  }

  function nextStep() {
    if (!validateStep()) return
    setStep(s => Math.min(s + 1, 5))
  }

  async function handleSubmit() {
    if (!validateStep()) return
    setSubmitting(true)
    setApiError('')
    const token = getToken()
    if (!token) { router.replace('/login'); return }
    try {
      await submitIntake(form, token)
      router.push('/dashboard')
    } catch (err) {
      setApiError(err instanceof Error ? err.message : 'Submission failed')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="min-h-screen py-8 px-4">
      <div className="max-w-2xl mx-auto">
        <div className="mb-8">
          <h1 className="text-2xl font-bold text-slate-900">Patient Intake Form</h1>
          <p className="text-slate-500 mt-1">Step {step} of 5 — {STEP_LABELS[step - 1]}</p>
          {/* Progress bar */}
          <div className="mt-4 flex gap-1">
            {STEP_LABELS.map((_, i) => (
              <div key={i} className={`h-2 flex-1 rounded-full ${i < step ? 'bg-blue-600' : 'bg-slate-200'}`} />
            ))}
          </div>
        </div>

        <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-8">
          {stepError && (
            <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">{stepError}</div>
          )}
          {apiError && (
            <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">{apiError}</div>
          )}

          {/* Step 1: Demographics placeholder (data comes from registration) */}
          {step === 1 && (
            <div className="space-y-4">
              <div className="p-4 bg-blue-50 rounded-lg">
                <p className="text-blue-800 text-sm">Your demographic information was collected during registration. Please continue to fill in your medical history.</p>
              </div>
              <p className="text-slate-600 text-sm">Click <strong>Next</strong> to proceed to the medical history section.</p>
            </div>
          )}

          {/* Step 2: Medical History */}
          {step === 2 && (
            <div className="space-y-6">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">Medical Conditions</label>
                <div className="flex gap-2">
                  <input
                    value={conditionInput} onChange={e => setConditionInput(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && (e.preventDefault(), addCondition())}
                    placeholder="e.g. Type 2 Diabetes" className="flex-1 px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                  <button type="button" onClick={addCondition} className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700">Add</button>
                </div>
                <div className="mt-2 flex flex-wrap gap-2">
                  {form.conditions.map(c => (
                    <span key={c} className="inline-flex items-center gap-1 px-3 py-1 bg-blue-100 text-blue-800 rounded-full text-sm">
                      {c}
                      <button onClick={() => removeCondition(c)} className="text-blue-600 hover:text-blue-800 ml-1">×</button>
                    </span>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* Step 3: Medications */}
          {step === 3 && (
            <div className="space-y-4">
              <label className="block text-sm font-medium text-slate-700">Current Medications</label>
              <div className="grid grid-cols-3 gap-2">
                <input value={medInputs.name} onChange={e => setMedInputs(m => ({ ...m, name: e.target.value }))} placeholder="Medication name" className="px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                <input value={medInputs.dose} onChange={e => setMedInputs(m => ({ ...m, dose: e.target.value }))} placeholder="Dose (e.g. 10mg)" className="px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                <input value={medInputs.frequency} onChange={e => setMedInputs(m => ({ ...m, frequency: e.target.value }))} placeholder="Frequency" className="px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
              <button type="button" onClick={addMedication} className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700">Add Medication</button>
              {form.medications.length > 0 && (
                <table className="w-full text-sm border-collapse">
                  <thead>
                    <tr className="bg-slate-50">
                      <th className="text-left py-2 px-3 font-medium text-slate-600 border-b">Name</th>
                      <th className="text-left py-2 px-3 font-medium text-slate-600 border-b">Dose</th>
                      <th className="text-left py-2 px-3 font-medium text-slate-600 border-b">Frequency</th>
                      <th className="py-2 px-3 border-b"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {form.medications.map((m, i) => (
                      <tr key={i} className="border-b border-slate-100 hover:bg-slate-50">
                        <td className="py-2 px-3">{m.name}</td>
                        <td className="py-2 px-3">{m.dose}</td>
                        <td className="py-2 px-3">{m.frequency}</td>
                        <td className="py-2 px-3 text-right">
                          <button onClick={() => removeMedication(i)} className="text-red-500 hover:text-red-700 text-xs">Remove</button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}

          {/* Step 4: Allergies */}
          {step === 4 && (
            <div className="space-y-4">
              <label className="block text-sm font-medium text-slate-700">Allergies</label>
              <div className="flex gap-2">
                <input
                  value={allergyInput} onChange={e => setAllergyInput(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && (e.preventDefault(), addAllergy())}
                  placeholder="e.g. Penicillin" className="flex-1 px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                <button type="button" onClick={addAllergy} className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700">Add</button>
              </div>
              <div className="flex flex-wrap gap-2">
                {form.allergies.map(a => (
                  <span key={a} className="inline-flex items-center gap-1 px-3 py-1 bg-red-100 text-red-800 rounded-full text-sm">
                    {a}
                    <button onClick={() => removeAllergy(a)} className="text-red-600 hover:text-red-800 ml-1">×</button>
                  </span>
                ))}
              </div>
              {form.allergies.length === 0 && (
                <p className="text-slate-400 text-sm italic">No allergies added. Add any known allergies above, or continue if you have none.</p>
              )}
            </div>
          )}

          {/* Step 5: Symptoms */}
          {step === 5 && (
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">Current Symptoms</label>
                <textarea
                  value={form.symptoms} onChange={e => setForm(f => ({ ...f, symptoms: e.target.value }))}
                  rows={5} placeholder="Please describe your current symptoms in detail. Include when they started, their severity, and anything that makes them better or worse."
                  className={`w-full px-3 py-2 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none ${form.symptoms.trim().length < 10 && form.symptoms.length > 0 ? 'border-red-400' : 'border-slate-300'}`}
                />
                <p className="text-xs text-slate-400 mt-1">{form.symptoms.trim().length} characters (minimum 10)</p>
              </div>

              {/* Review summary */}
              <div className="mt-6 p-4 bg-slate-50 rounded-lg text-sm space-y-2">
                <p className="font-medium text-slate-700">Review Summary</p>
                <p className="text-slate-600"><span className="font-medium">Conditions:</span> {form.conditions.join(', ') || 'None'}</p>
                <p className="text-slate-600"><span className="font-medium">Medications:</span> {form.medications.length} added</p>
                <p className="text-slate-600"><span className="font-medium">Allergies:</span> {form.allergies.join(', ') || 'None'}</p>
              </div>
            </div>
          )}

          <div className="flex justify-between mt-8">
            <button
              type="button" onClick={() => { setStep(s => Math.max(s - 1, 1)); setStepError('') }}
              disabled={step === 1}
              className="px-6 py-2.5 text-slate-600 bg-slate-100 hover:bg-slate-200 disabled:opacity-40 rounded-lg font-medium text-sm transition-colors"
            >
              Back
            </button>
            {step < 5 ? (
              <button type="button" onClick={nextStep} className="px-6 py-2.5 bg-blue-600 hover:bg-blue-700 text-white rounded-lg font-medium text-sm transition-colors">
                Next →
              </button>
            ) : (
              <button
                type="button" onClick={handleSubmit} disabled={submitting}
                className="px-6 py-2.5 bg-green-600 hover:bg-green-700 disabled:opacity-50 text-white rounded-lg font-medium text-sm transition-colors"
              >
                {submitting ? 'Submitting...' : 'Submit Intake Form'}
              </button>
            )}
          </div>
        </div>
      </div>
    </main>
  )
}
