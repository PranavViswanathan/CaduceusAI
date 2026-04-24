'use client'

import { useState, useRef, useEffect, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { agentQuery, getPatients, AgentQueryResponse, PatientListItem } from '@/lib/api'
import { getDoctorId } from '@/lib/auth'

type Message = {
  id: number
  role: 'user' | 'agent'
  text: string
  response?: AgentQueryResponse
}

const LOADING_MESSAGES = [
  'Fetching clinical context...',
  'Analyzing your query...',
  'Searching knowledge base...',
  'Reasoning through the evidence...',
  'Cross-referencing guidelines...',
  'Almost there, please hold...',
  'Compiling the response...',
]

const QUERY_TYPE_LABEL: Record<string, { label: string; cls: string }> = {
  routine: { label: 'Routine', cls: 'bg-slate-100 text-slate-600' },
  complex: { label: 'Complex', cls: 'bg-amber-100 text-amber-700' },
  urgent: { label: 'Urgent', cls: 'bg-red-100 text-red-700' },
}

export default function AgentPage() {
  const router = useRouter()
  const [patients, setPatients] = useState<PatientListItem[]>([])
  const [selectedPatientId, setSelectedPatientId] = useState<string>('')
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [loadingMsg, setLoadingMsg] = useState(LOADING_MESSAGES[0])
  const [error, setError] = useState('')
  const [showCot, setShowCot] = useState<number | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const msgId = useRef(0)
  const loadingMsgRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    if (!getDoctorId()) { router.replace('/login'); return }
    getPatients().then(setPatients).catch(() => {})
  }, [router])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const startLoadingMessages = useCallback(() => {
    let idx = 0
    setLoadingMsg(LOADING_MESSAGES[0])
    loadingMsgRef.current = setInterval(() => {
      idx = (idx + 1) % LOADING_MESSAGES.length
      setLoadingMsg(LOADING_MESSAGES[idx])
    }, 2500)
  }, [])

  const stopLoadingMessages = useCallback(() => {
    if (loadingMsgRef.current) {
      clearInterval(loadingMsgRef.current)
      loadingMsgRef.current = null
    }
  }, [])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const query = input.trim()
    if (!query || loading) return

    const userMsg: Message = { id: ++msgId.current, role: 'user', text: query }
    setMessages(prev => [...prev, userMsg])
    setInput('')
    setLoading(true)
    setError('')
    startLoadingMessages()

    try {
      const response = await agentQuery(query, selectedPatientId || undefined)
      const agentMsg: Message = {
        id: ++msgId.current,
        role: 'agent',
        text: response.response,
        response,
      }
      setMessages(prev => [...prev, agentMsg])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Agent query failed')
    } finally {
      stopLoadingMessages()
      setLoading(false)
    }
  }

  return (
    <main className="min-h-screen py-8 px-4 flex flex-col">
      <div className="max-w-3xl mx-auto w-full flex flex-col flex-1">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-slate-900">Clinical Agent</h1>
            <p className="text-slate-500 text-sm mt-0.5">LangGraph-powered clinical reasoning assistant</p>
          </div>
          <Link href="/patients" className="px-4 py-2 text-slate-600 bg-white hover:bg-slate-50 border border-slate-200 rounded-lg text-sm font-medium transition-colors">
            ← Patients
          </Link>
        </div>

        {/* Patient context selector */}
        <div className="mb-4">
          <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">
            Patient context (optional)
          </label>
          <select
            value={selectedPatientId}
            onChange={e => setSelectedPatientId(e.target.value)}
            className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">No specific patient — general query</option>
            {patients.map(p => (
              <option key={p.id} value={p.id}>{p.name} ({p.email})</option>
            ))}
          </select>
        </div>

        {/* Chat window */}
        <div className="flex-1 bg-white rounded-2xl border border-slate-200 shadow-sm overflow-y-auto p-4 space-y-4 mb-4 min-h-[400px] max-h-[60vh]">
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center h-full text-center py-16">
              <div className="w-14 h-14 bg-blue-50 rounded-2xl flex items-center justify-center mb-4">
                <span className="text-2xl">🩺</span>
              </div>
              <p className="text-slate-700 font-semibold">Ask the clinical agent anything</p>
              <p className="text-slate-400 text-sm mt-1 max-w-xs">
                Drug interactions, care plan questions, symptom triage, or patient-specific queries.
              </p>
            </div>
          )}

          {messages.map(msg => (
            <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              {msg.role === 'user' ? (
                <div className="max-w-[80%] bg-blue-900 text-white rounded-2xl rounded-br-sm px-4 py-3 text-sm">
                  {msg.text}
                </div>
              ) : (
                <div className="max-w-[85%] space-y-2">
                  <div className="bg-slate-50 border border-slate-200 rounded-2xl rounded-bl-sm px-4 py-3">
                    {/* Badges */}
                    {msg.response && (
                      <div className="flex flex-wrap items-center gap-2 mb-2">
                        <span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${QUERY_TYPE_LABEL[msg.response.query_type]?.cls ?? 'bg-slate-100 text-slate-600'}`}>
                          {QUERY_TYPE_LABEL[msg.response.query_type]?.label ?? msg.response.query_type}
                        </span>
                        <span className="text-xs text-slate-400">
                          Confidence: {(msg.response.confidence * 100).toFixed(0)}%
                        </span>
                        {msg.response.requires_escalation && (
                          <span className="px-2 py-0.5 bg-red-100 text-red-700 rounded-full text-xs font-semibold">
                            Escalated
                          </span>
                        )}
                      </div>
                    )}

                    <p className="text-sm text-slate-800 leading-relaxed whitespace-pre-wrap">{msg.text}</p>

                    {msg.response?.requires_escalation && msg.response.escalation_id && (
                      <div className="mt-2 p-2 bg-red-50 border border-red-100 rounded-lg text-xs text-red-700">
                        Escalation created — ID: <span className="font-mono">{msg.response.escalation_id}</span>
                      </div>
                    )}
                  </div>

                  {/* Chain of thought toggle */}
                  {msg.response?.chain_of_thought && (
                    <button
                      onClick={() => setShowCot(showCot === msg.id ? null : msg.id)}
                      className="text-xs text-slate-400 hover:text-slate-600 px-1"
                    >
                      {showCot === msg.id ? '▲ Hide reasoning' : '▼ Show reasoning'}
                    </button>
                  )}
                  {showCot === msg.id && msg.response?.chain_of_thought && (
                    <div className="bg-slate-50 border border-slate-200 rounded-xl px-4 py-3 text-xs text-slate-600 leading-relaxed font-mono whitespace-pre-wrap">
                      {msg.response.chain_of_thought}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}

          {loading && (
            <div className="flex justify-start">
              <div className="bg-slate-50 border border-slate-200 rounded-2xl rounded-bl-sm px-4 py-3 flex items-center gap-2 min-w-[220px]">
                <div className="w-4 h-4 border-2 border-blue-600 border-t-transparent rounded-full animate-spin flex-shrink-0" />
                <span key={loadingMsg} className="text-sm text-slate-500 animate-pulse">{loadingMsg}</span>
              </div>
            </div>
          )}

          <div ref={bottomRef} />
        </div>

        {error && (
          <p className="mb-3 text-sm text-red-600 px-1">{error}</p>
        )}

        {/* Input */}
        <form onSubmit={handleSubmit} className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={e => setInput(e.target.value)}
            placeholder="Ask a clinical question..."
            disabled={loading}
            className="flex-1 px-4 py-3 border border-slate-300 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-60"
          />
          <button
            type="submit"
            disabled={!input.trim() || loading}
            className="px-5 py-3 bg-blue-900 hover:bg-blue-800 disabled:opacity-40 text-white text-sm font-semibold rounded-xl transition-colors"
          >
            Send
          </button>
        </form>
      </div>
    </main>
  )
}
