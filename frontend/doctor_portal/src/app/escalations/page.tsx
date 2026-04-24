'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { getAgentEscalations, acknowledgeAgentEscalation, AgentEscalation } from '@/lib/api'
import { getDoctorId } from '@/lib/auth'

const QUERY_TYPE_STYLE: Record<string, string> = {
  urgent: 'bg-red-100 text-red-700',
  complex: 'bg-amber-100 text-amber-700',
  routine: 'bg-slate-100 text-slate-600',
}

export default function EscalationsPage() {
  const router = useRouter()
  const [escalations, setEscalations] = useState<AgentEscalation[]>([])
  const [loading, setLoading] = useState(true)
  const [acknowledging, setAcknowledging] = useState<string | null>(null)

  useEffect(() => {
    if (!getDoctorId()) { router.replace('/login'); return }
    getAgentEscalations()
      .then(setEscalations)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [router])

  async function handleAcknowledge(id: string) {
    setAcknowledging(id)
    try {
      await acknowledgeAgentEscalation(id)
      setEscalations(prev => prev.filter(e => e.id !== id))
    } catch {
      // keep in list if it fails
    } finally {
      setAcknowledging(null)
    }
  }

  return (
    <main className="min-h-screen py-8 px-4">
      <div className="max-w-3xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-slate-900">Agent Escalations</h1>
            <p className="text-slate-500 text-sm mt-0.5">Queries flagged for clinician review</p>
          </div>
          <Link href="/patients" className="px-4 py-2 text-slate-600 bg-white hover:bg-slate-50 border border-slate-200 rounded-lg text-sm font-medium transition-colors">
            ← Patients
          </Link>
        </div>

        {loading ? (
          <div className="flex items-center gap-3 py-16 text-slate-400 justify-center">
            <div className="w-5 h-5 border-2 border-blue-600 border-t-transparent rounded-full animate-spin" />
            <span className="text-sm">Loading escalations...</span>
          </div>
        ) : escalations.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <div className="w-14 h-14 bg-green-50 rounded-2xl flex items-center justify-center mb-4">
              <span className="text-2xl">✓</span>
            </div>
            <p className="text-slate-700 font-semibold">No pending escalations</p>
            <p className="text-slate-400 text-sm mt-1">All agent queries have been reviewed</p>
          </div>
        ) : (
          <div className="space-y-3">
            {escalations.map(esc => (
              <div key={esc.id} className="bg-white rounded-2xl border border-slate-200 shadow-sm p-5">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-2">
                      <span className={`px-2 py-0.5 rounded-full text-xs font-semibold capitalize ${QUERY_TYPE_STYLE[esc.query_type] ?? 'bg-slate-100 text-slate-600'}`}>
                        {esc.query_type}
                      </span>
                      {esc.patient_name && (
                        <span className="text-xs text-slate-500">
                          Patient: <span className="font-medium text-slate-700">{esc.patient_name}</span>
                        </span>
                      )}
                      <span className="text-xs text-slate-400 ml-auto">
                        {new Date(esc.created_at).toLocaleString()}
                      </span>
                    </div>

                    <p className="text-sm text-slate-800 font-medium mb-1">Query</p>
                    <p className="text-sm text-slate-600 bg-slate-50 rounded-lg px-3 py-2 mb-3">
                      {esc.query}
                    </p>

                    {esc.reason && (
                      <>
                        <p className="text-sm text-slate-800 font-medium mb-1">Reason for escalation</p>
                        <p className="text-xs text-slate-500">{esc.reason}</p>
                      </>
                    )}
                  </div>
                </div>

                <div className="mt-4 flex justify-end">
                  <button
                    onClick={() => handleAcknowledge(esc.id)}
                    disabled={acknowledging === esc.id}
                    className="px-4 py-2 bg-blue-900 hover:bg-blue-800 disabled:opacity-40 text-white text-sm font-semibold rounded-lg transition-colors"
                  >
                    {acknowledging === esc.id ? 'Acknowledging...' : 'Acknowledge & Dismiss'}
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </main>
  )
}
