'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import { useRouter, useParams } from 'next/navigation'
import Link from 'next/link'
import {
  getPatients, getPatientRisk, submitFeedback,
  PatientListItem, RiskAssessment, FeedbackPayload
} from '@/lib/api'
import { getDoctorId } from '@/lib/auth'

const POLL_INTERVAL = 60

type FeedbackAction = 'agree' | 'override' | 'flag'

export default function PatientDetailPage() {
  const router = useRouter()
  const params = useParams()
  const patientId = params.id as string

  const [patient, setPatient] = useState<PatientListItem | null>(null)
  const [risk, setRisk] = useState<RiskAssessment | null>(null)
  const [loadingPatient, setLoadingPatient] = useState(true)
  const [loadingRisk, setLoadingRisk] = useState(true)
  const [riskError, setRiskError] = useState(false)
  const [countdown, setCountdown] = useState(POLL_INTERVAL)

  // Feedback state
  const [feedbackAction, setFeedbackAction] = useState<FeedbackAction | null>(null)
  const [overrideReason, setOverrideReason] = useState('')
  const [feedbackSubmitting, setFeedbackSubmitting] = useState(false)
  const [feedbackSuccess, setFeedbackSuccess] = useState(false)
  const [feedbackError, setFeedbackError] = useState('')

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const countdownRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const fetchRisk = useCallback(async () => {
    setLoadingRisk(true)
    setRiskError(false)
    try {
      const data = await getPatientRisk(patientId)
      setRisk(data)
    } catch {
      setRiskError(true)
    } finally {
      setLoadingRisk(false)
    }
  }, [patientId])

  useEffect(() => {
    if (!getDoctorId()) { router.replace('/login'); return }

    // Load patient from list
    getPatients().then(list => {
      const found = list.find(p => p.id === patientId) || null
      setPatient(found)
    }).catch(() => {}).finally(() => setLoadingPatient(false))

    // Load risk assessment
    fetchRisk()

    // Poll every 60 seconds
    pollRef.current = setInterval(() => {
      fetchRisk()
      setCountdown(POLL_INTERVAL)
    }, POLL_INTERVAL * 1000)

    // Countdown timer
    countdownRef.current = setInterval(() => {
      setCountdown(c => Math.max(c - 1, 0))
    }, 1000)

    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
      if (countdownRef.current) clearInterval(countdownRef.current)
    }
  }, [patientId, router, fetchRisk])

  async function handleFeedbackSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!feedbackAction) return
    if (feedbackAction === 'override' && !overrideReason.trim()) {
      setFeedbackError('Please provide your clinical reasoning')
      return
    }
    const doctorId = getDoctorId()
    if (!doctorId) { router.replace('/login'); return }

    setFeedbackSubmitting(true)
    setFeedbackError('')
    try {
      const payload: FeedbackPayload = {
        action: feedbackAction,
        reason: overrideReason || undefined,
        doctor_id: doctorId,
        assessment_id: risk?.id,
      }
      await submitFeedback(patientId, payload)
      setFeedbackSuccess(true)
      setTimeout(() => setFeedbackSuccess(false), 4000)
      setFeedbackAction(null)
      setOverrideReason('')
    } catch (err) {
      setFeedbackError(err instanceof Error ? err.message : 'Failed to submit feedback')
    } finally {
      setFeedbackSubmitting(false)
    }
  }

  const confidenceBadge = (c: string) => {
    if (c === 'high') return <span className="px-2.5 py-1 bg-green-100 text-green-800 rounded-full text-xs font-semibold">High Confidence</span>
    if (c === 'medium') return <span className="px-2.5 py-1 bg-amber-100 text-amber-800 rounded-full text-xs font-semibold">Medium Confidence</span>
    return <span className="px-2.5 py-1 bg-red-100 text-red-800 rounded-full text-xs font-semibold">Low Confidence</span>
  }

  return (
    <main className="min-h-screen py-8 px-4">
      <div className="max-w-6xl mx-auto">
        {/* Breadcrumb */}
        <div className="flex items-center gap-2 text-sm text-slate-500 mb-6">
          <Link href="/patients" className="hover:text-slate-700">Patients</Link>
          <span>›</span>
          <span className="text-slate-900 font-medium">{loadingPatient ? '...' : (patient?.name || 'Unknown Patient')}</span>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
          {/* Left column: Patient Record (40%) */}
          <div className="lg:col-span-2 space-y-4">
            <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
              <h2 className="text-lg font-bold text-slate-900 mb-1">
                {loadingPatient ? <span className="h-6 w-40 bg-slate-100 rounded animate-pulse inline-block" /> : (patient?.name || 'Unknown Patient')}
              </h2>
              <p className="text-slate-400 text-sm">{patient?.email}</p>

              {patient?.intake_submitted_at ? (
                <p className="text-xs text-green-600 mt-1">
                  Intake submitted {new Date(patient.intake_submitted_at).toLocaleDateString()}
                </p>
              ) : (
                <p className="text-xs text-amber-600 mt-1">No intake submitted</p>
              )}
            </div>

            <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">Record Details</p>
              <p className="text-sm text-slate-500 italic">
                Full demographics and medication list are fetched server-side during risk assessment.
                View the AI analysis panel for condition and medication context.
              </p>
            </div>
          </div>

          {/* Right column: Risk Panel (60%) */}
          <div className="lg:col-span-3 space-y-4">
            {/* Risk Assessment Panel */}
            <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-bold text-slate-900">AI Risk Assessment</h2>
                <div className="flex items-center gap-3">
                  <span className="text-xs text-slate-400">Auto-refresh in {countdown}s</span>
                  <button
                    onClick={() => { fetchRisk(); setCountdown(POLL_INTERVAL) }}
                    className="text-xs text-blue-600 hover:text-blue-800 font-medium"
                  >
                    Refresh ↺
                  </button>
                </div>
              </div>

              {loadingRisk ? (
                <div className="flex items-center gap-3 py-8 text-slate-400">
                  <div className="w-5 h-5 border-2 border-blue-600 border-t-transparent rounded-full animate-spin flex-shrink-0" />
                  <span className="text-sm">Analyzing patient data...</span>
                </div>
              ) : riskError ? (
                <div className="p-4 bg-amber-50 border border-amber-200 rounded-lg">
                  <p className="text-amber-800 font-medium text-sm">Risk assessment unavailable</p>
                  <p className="text-amber-700 text-xs mt-0.5">Could not connect to the assessment service. Please retry.</p>
                </div>
              ) : risk ? (
                <div className="space-y-4">
                  {/* Source banner */}
                  {risk.source === 'rule_based' ? (
                    <div className="flex items-center gap-2 p-3 bg-amber-50 border border-amber-200 rounded-lg">
                      <span className="text-amber-500">⚠</span>
                      <span className="text-amber-800 text-sm font-medium">AI unavailable — showing rule-based warnings only</span>
                    </div>
                  ) : (
                    <div className="flex items-center gap-2 p-3 bg-blue-50 border border-blue-200 rounded-lg">
                      <span className="text-blue-500">🤖</span>
                      <span className="text-blue-800 text-sm font-medium">Powered by AI analysis</span>
                    </div>
                  )}

                  {/* Confidence */}
                  <div className="flex items-center gap-2">
                    {confidenceBadge(risk.confidence)}
                    <span className="text-xs text-slate-400">Assessment v{risk.version}</span>
                  </div>

                  {/* Risks */}
                  {risk.risks.length > 0 && (
                    <div>
                      <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Identified Risks</p>
                      <div className="space-y-2">
                        {risk.risks.map((r, i) => (
                          <div key={i} className="flex items-start gap-2.5 p-3 bg-red-50 border border-red-100 rounded-lg">
                            <span className="text-red-500 flex-shrink-0 mt-0.5">⚠</span>
                            <span className="text-sm text-red-800">{r}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Summary */}
                  <div>
                    <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Clinical Summary</p>
                    <div className="p-3 bg-slate-50 rounded-lg">
                      <p className="text-sm text-slate-700 leading-relaxed">{risk.summary}</p>
                    </div>
                  </div>

                  <p className="text-xs text-slate-400">
                    Generated {new Date(risk.created_at).toLocaleString()}
                  </p>
                </div>
              ) : null}
            </div>

            {/* Feedback Form */}
            <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
              <h3 className="font-bold text-slate-900 mb-4">Clinician Feedback</h3>

              {feedbackSuccess && (
                <div className="mb-4 p-3 bg-green-50 border border-green-200 rounded-lg text-green-700 text-sm flex items-center gap-2">
                  <span>✓</span> Feedback recorded successfully
                </div>
              )}

              <form onSubmit={handleFeedbackSubmit}>
                <div className="space-y-2 mb-4">
                  {(['agree', 'override', 'flag'] as FeedbackAction[]).map(action => (
                    <label
                      key={action}
                      className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${feedbackAction === action ? 'border-blue-500 bg-blue-50' : 'border-slate-200 hover:bg-slate-50'}`}
                    >
                      <input
                        type="radio" name="feedback" value={action}
                        checked={feedbackAction === action}
                        onChange={() => { setFeedbackAction(action); setFeedbackError('') }}
                        className="mt-0.5"
                      />
                      <div>
                        <p className="text-sm font-medium text-slate-900">
                          {action === 'agree' && '✓ Agree'}
                          {action === 'override' && '✏ Override'}
                          {action === 'flag' && '🚩 Flag for Review'}
                        </p>
                        <p className="text-xs text-slate-500">
                          {action === 'agree' && 'I agree with this assessment'}
                          {action === 'override' && 'I disagree and will provide an alternative assessment'}
                          {action === 'flag' && 'Flag this case for peer review'}
                        </p>
                      </div>
                    </label>
                  ))}
                </div>

                {feedbackAction === 'override' && (
                  <div className="mb-4">
                    <label className="block text-sm font-medium text-slate-700 mb-1">Clinical Reasoning (required)</label>
                    <textarea
                      value={overrideReason} onChange={e => setOverrideReason(e.target.value)}
                      rows={3} placeholder="Provide your clinical assessment and reasoning..."
                      className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
                    />
                  </div>
                )}

                {feedbackError && (
                  <p className="mb-3 text-sm text-red-600">{feedbackError}</p>
                )}

                <button
                  type="submit"
                  disabled={!feedbackAction || feedbackSubmitting}
                  className="w-full bg-blue-900 hover:bg-blue-800 disabled:opacity-40 text-white font-semibold py-2.5 rounded-lg text-sm transition-colors"
                >
                  {feedbackSubmitting ? 'Submitting...' : 'Submit Feedback'}
                </button>
              </form>
            </div>
          </div>
        </div>
      </div>
    </main>
  )
}
