'use client'

import { useState, useEffect, useRef } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { getPatients, getPendingEscalations, getRetrainStatus, PatientListItem, Escalation, RetrainStatus } from '@/lib/api'
import { getDoctorId, logout } from '@/lib/auth'

export default function PatientsPage() {
  const router = useRouter()
  const [patients, setPatients] = useState<PatientListItem[]>([])
  const [escalations, setEscalations] = useState<Escalation[]>([])
  const [retrainStatus, setRetrainStatus] = useState<RetrainStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  async function loadEscalations() {
    try {
      const data = await getPendingEscalations()
      setEscalations(data)
    } catch {
      // silent — escalation polling failures don't block the main UI
    }
  }

  useEffect(() => {
    if (!getDoctorId()) { router.replace('/login'); return }

    Promise.all([getPatients(), getPendingEscalations(), getRetrainStatus()])
      .then(([p, e, r]) => { setPatients(p); setEscalations(e); setRetrainStatus(r) })
      .catch(err => setError(err instanceof Error ? err.message : 'Failed to load'))
      .finally(() => setLoading(false))

    // Poll escalations every 60 seconds
    intervalRef.current = setInterval(loadEscalations, 60_000)
    return () => { if (intervalRef.current) clearInterval(intervalRef.current) }
  }, [router])

  async function handleLogout() {
    await logout()
    router.push('/login')
  }

  if (loading) {
    return (
      <main className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <div className="w-8 h-8 border-4 border-blue-900 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
          <p className="text-slate-500 text-sm">Loading patient list...</p>
        </div>
      </main>
    )
  }

  return (
    <main className="min-h-screen py-8 px-4">
      <div className="max-w-5xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-slate-900">Patient Overview</h1>
            <p className="text-slate-500 text-sm mt-0.5">{patients.length} patient{patients.length !== 1 ? 's' : ''} registered</p>
          </div>
          <button onClick={handleLogout} className="px-4 py-2 text-slate-600 bg-white hover:bg-slate-50 border border-slate-200 rounded-lg text-sm font-medium transition-colors">
            Sign Out
          </button>
        </div>

        {/* Escalation banner */}
        {escalations.length > 0 && (
          <div className="mb-6 flex items-center gap-3 p-4 bg-red-50 border border-red-300 rounded-xl">
            <div className="w-8 h-8 bg-red-100 rounded-full flex items-center justify-center flex-shrink-0">
              <span className="text-red-600 text-sm font-bold">!</span>
            </div>
            <div className="flex-1">
              <p className="text-red-800 font-semibold text-sm">
                {escalations.length} pending escalation{escalations.length !== 1 ? 's' : ''} — review required
              </p>
              <p className="text-red-600 text-xs mt-0.5">
                {escalations.map(e => e.patient_name).join(', ')}
              </p>
            </div>
          </div>
        )}

        {/* Retrain queue status bar */}
        {retrainStatus && (
          <div className="mb-6 flex flex-wrap items-center gap-4 px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-sm">
            <div className="flex items-center gap-1.5">
              <span className="text-slate-500">Retrain queue:</span>
              <span className="font-semibold text-slate-800">{retrainStatus.queued_count}</span>
              <span className="text-slate-400">/ {retrainStatus.min_batch} needed</span>
            </div>
            {retrainStatus.items_needed > 0 ? (
              <span className="px-2 py-0.5 bg-amber-100 text-amber-700 rounded-full text-xs font-medium">
                {retrainStatus.items_needed} more override{retrainStatus.items_needed !== 1 ? 's' : ''} to trigger retrain
              </span>
            ) : (
              <span className="px-2 py-0.5 bg-green-100 text-green-700 rounded-full text-xs font-medium">
                Ready to retrain
              </span>
            )}
            {retrainStatus.last_run && (
              <div className="flex items-center gap-2 ml-auto text-xs text-slate-500">
                <span>Last run: <span className="font-mono text-slate-700">{retrainStatus.last_run.version}</span></span>
                <span className={`px-1.5 py-0.5 rounded-full font-medium ${
                  retrainStatus.last_run.status === 'success' ? 'bg-green-100 text-green-700' :
                  retrainStatus.last_run.status === 'eval_failed' ? 'bg-yellow-100 text-yellow-700' :
                  'bg-red-100 text-red-700'
                }`}>{retrainStatus.last_run.status}</span>
                {retrainStatus.last_run.override_rate !== undefined && (
                  <span>Override rate: <span className="font-medium text-slate-700">{(retrainStatus.last_run.override_rate * 100).toFixed(0)}%</span></span>
                )}
              </div>
            )}
          </div>
        )}

        {error && (
          <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-xl text-red-700 text-sm">{error}</div>
        )}

        {/* Patient table */}
        <div className="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200">
                <th className="text-left py-3 px-6 text-xs font-semibold text-slate-500 uppercase tracking-wide">Patient</th>
                <th className="text-left py-3 px-6 text-xs font-semibold text-slate-500 uppercase tracking-wide">Email</th>
                <th className="text-left py-3 px-6 text-xs font-semibold text-slate-500 uppercase tracking-wide">Intake Status</th>
                <th className="py-3 px-6"></th>
              </tr>
            </thead>
            <tbody>
              {patients.length === 0 ? (
                <tr>
                  <td colSpan={4} className="text-center py-12 text-slate-400 text-sm">No patients registered yet</td>
                </tr>
              ) : (
                patients.map((p, i) => (
                  <tr key={p.id} className={`border-b border-slate-100 hover:bg-slate-50 transition-colors ${i % 2 === 0 ? '' : 'bg-slate-50/50'}`}>
                    <td className="py-4 px-6">
                      <p className="font-medium text-slate-900 text-sm">{p.name}</p>
                    </td>
                    <td className="py-4 px-6 text-slate-500 text-sm">{p.email}</td>
                    <td className="py-4 px-6">
                      {p.intake_submitted_at ? (
                        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-green-100 text-green-800 rounded-full text-xs font-medium">
                          <span className="w-1.5 h-1.5 bg-green-500 rounded-full" />
                          Submitted
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-slate-100 text-slate-500 rounded-full text-xs font-medium">
                          <span className="w-1.5 h-1.5 bg-slate-400 rounded-full" />
                          Pending
                        </span>
                      )}
                    </td>
                    <td className="py-4 px-6 text-right">
                      <Link href={`/patients/${p.id}`} className="text-blue-600 hover:text-blue-800 text-sm font-medium hover:underline">
                        View →
                      </Link>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </main>
  )
}
