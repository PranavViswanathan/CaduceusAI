'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { getPatient, getCarePlan, PatientData, CarePlanData } from '@/lib/api'
import { getPatientId, logout } from '@/lib/auth'

export default function DashboardPage() {
  const router = useRouter()
  const [patient, setPatient] = useState<PatientData | null>(null)
  const [carePlan, setCarePlan] = useState<CarePlanData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const patientId = getPatientId()
    if (!patientId) { router.replace('/login'); return }

    Promise.all([
      getPatient(patientId),
      getCarePlan(patientId),
    ])
      .then(([p, cp]) => { setPatient(p); setCarePlan(cp) })
      .catch(err => setError(err instanceof Error ? err.message : 'Failed to load records'))
      .finally(() => setLoading(false))
  }, [router])

  async function handleLogout() {
    await logout()
    router.push('/')
  }

  if (loading) {
    return (
      <main className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <div className="w-8 h-8 border-4 border-blue-600 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
          <p className="text-slate-500 text-sm">Loading your health records...</p>
        </div>
      </main>
    )
  }

  if (error) {
    return (
      <main className="flex items-center justify-center min-h-screen p-8">
        <div className="bg-red-50 border border-red-200 rounded-xl p-6 text-center max-w-md">
          <p className="text-red-700 font-medium mb-2">Unable to load records</p>
          <p className="text-red-600 text-sm mb-4">{error}</p>
          <button onClick={handleLogout} className="text-sm text-blue-600 hover:underline">Sign out and try again</button>
        </div>
      </main>
    )
  }

  const intake = patient?.intake

  return (
    <main className="min-h-screen py-8 px-4">
      <div className="max-w-5xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold text-slate-900">Welcome, {patient?.name}</h1>
            <p className="text-slate-500 text-sm mt-0.5">{patient?.email}</p>
          </div>
          <div className="flex items-center gap-3">
            {!intake && (
              <Link href="/intake" className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-medium transition-colors">
                Complete Intake
              </Link>
            )}
            <button onClick={handleLogout} className="px-4 py-2 text-slate-600 hover:text-slate-900 bg-slate-100 hover:bg-slate-200 rounded-lg text-sm font-medium transition-colors">
              Sign Out
            </button>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Left: Patient Information */}
          <div className="space-y-6">
            {/* Demographics */}
            <section className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
              <h2 className="text-sm font-semibold text-blue-700 uppercase tracking-wide mb-4">Patient Information</h2>
              <div className="grid grid-cols-2 gap-3 text-sm">
                <Info label="Date of Birth" value={patient?.dob || '—'} />
                <Info label="Sex" value={patient?.sex || '—'} />
                <Info label="Phone" value={patient?.phone || '—'} />
                <Info label="Member Since" value={patient?.created_at ? new Date(patient.created_at).toLocaleDateString() : '—'} />
              </div>
            </section>

            {intake ? (
              <>
                {/* Conditions */}
                {intake.conditions.length > 0 && (
                  <section className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
                    <h2 className="text-sm font-semibold text-blue-700 uppercase tracking-wide mb-3">Medical Conditions</h2>
                    <div className="flex flex-wrap gap-2">
                      {intake.conditions.map(c => (
                        <span key={c} className="px-3 py-1 bg-blue-100 text-blue-800 rounded-full text-sm">{c}</span>
                      ))}
                    </div>
                  </section>
                )}

                {/* Medications */}
                {intake.medications.length > 0 && (
                  <section className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
                    <h2 className="text-sm font-semibold text-amber-700 uppercase tracking-wide mb-3">Current Medications</h2>
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="text-left text-slate-500 border-b border-slate-100">
                          <th className="pb-2 font-medium">Medication</th>
                          <th className="pb-2 font-medium">Dose</th>
                          <th className="pb-2 font-medium">Frequency</th>
                        </tr>
                      </thead>
                      <tbody>
                        {intake.medications.map((m, i) => (
                          <tr key={i} className="border-b border-slate-50">
                            <td className="py-2">{m.name}</td>
                            <td className="py-2 text-slate-600">{m.dose}</td>
                            <td className="py-2 text-slate-600">{m.frequency}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </section>
                )}

                {/* Allergies */}
                {intake.allergies.length > 0 && (
                  <section className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
                    <h2 className="text-sm font-semibold text-red-700 uppercase tracking-wide mb-3">Allergies</h2>
                    <div className="flex flex-wrap gap-2">
                      {intake.allergies.map(a => (
                        <span key={a} className="px-3 py-1 bg-red-100 text-red-800 rounded-full text-sm">{a}</span>
                      ))}
                    </div>
                  </section>
                )}

                {/* Symptoms */}
                {intake.symptoms && (
                  <section className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
                    <h2 className="text-sm font-semibold text-slate-600 uppercase tracking-wide mb-3">Reported Symptoms</h2>
                    <p className="text-sm text-slate-700 bg-slate-50 rounded-lg p-3 leading-relaxed">{intake.symptoms}</p>
                    <p className="text-xs text-slate-400 mt-2">Submitted {new Date(intake.submitted_at).toLocaleString()}</p>
                  </section>
                )}
              </>
            ) : (
              <div className="bg-amber-50 border border-amber-200 rounded-xl p-6 text-center">
                <p className="text-amber-800 font-medium">No intake form submitted yet</p>
                <p className="text-amber-700 text-sm mt-1">Please complete your intake form to receive personalized care.</p>
                <Link href="/intake" className="inline-block mt-3 px-4 py-2 bg-amber-600 hover:bg-amber-700 text-white rounded-lg text-sm font-medium transition-colors">
                  Start Intake Form
                </Link>
              </div>
            )}
          </div>

          {/* Right: Care Plan */}
          <div>
            <section className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
              <h2 className="text-sm font-semibold text-slate-700 uppercase tracking-wide mb-4">Care Plan & Messages</h2>
              {!carePlan ? (
                <div className="text-center py-8 text-slate-400">
                  <svg className="w-12 h-12 mx-auto mb-3 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                  <p className="text-sm font-medium text-slate-500">No care plan yet</p>
                  <p className="text-xs mt-1">Your doctor will generate a personalized care plan after reviewing your intake.</p>
                </div>
              ) : (
                <div className="space-y-5">
                  {carePlan.follow_up_date && (
                    <div className="flex items-center gap-3 p-3 bg-blue-50 rounded-lg">
                      <svg className="w-5 h-5 text-blue-600 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                      </svg>
                      <div>
                        <p className="text-xs font-medium text-blue-700">Follow-up Date</p>
                        <p className="text-sm text-blue-900">{new Date(carePlan.follow_up_date).toLocaleDateString('en-US', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })}</p>
                      </div>
                    </div>
                  )}

                  {carePlan.medications_to_monitor.length > 0 && (
                    <div>
                      <p className="text-xs font-semibold text-amber-700 uppercase tracking-wide mb-2">Medications to Monitor</p>
                      <ul className="space-y-1">
                        {carePlan.medications_to_monitor.map((m, i) => (
                          <li key={i} className="text-sm text-slate-700 flex items-start gap-2">
                            <span className="text-amber-500 mt-0.5">•</span>{m}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {carePlan.lifestyle_recommendations.length > 0 && (
                    <div>
                      <p className="text-xs font-semibold text-green-700 uppercase tracking-wide mb-2">Lifestyle Recommendations</p>
                      <ul className="space-y-1">
                        {carePlan.lifestyle_recommendations.map((r, i) => (
                          <li key={i} className="text-sm text-slate-700 flex items-start gap-2">
                            <span className="text-green-500 mt-0.5">✓</span>{r}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {carePlan.warning_signs.length > 0 && (
                    <div>
                      <p className="text-xs font-semibold text-red-700 uppercase tracking-wide mb-2">Call Your Doctor If You Experience</p>
                      <div className="space-y-1.5">
                        {carePlan.warning_signs.map((w, i) => (
                          <div key={i} className="flex items-start gap-2 p-2 bg-red-50 rounded-lg">
                            <span className="text-red-500 text-sm mt-0.5">⚠</span>
                            <span className="text-sm text-red-800">{w}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  <p className="text-xs text-slate-400 pt-2 border-t border-slate-100">
                    Plan generated {new Date(carePlan.created_at).toLocaleDateString()}
                  </p>
                </div>
              )}
            </section>
          </div>
        </div>
      </div>
    </main>
  )
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-slate-400 font-medium">{label}</p>
      <p className="text-slate-800">{value}</p>
    </div>
  )
}
