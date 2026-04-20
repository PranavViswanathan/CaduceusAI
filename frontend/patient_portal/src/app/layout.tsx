import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'Patient Portal | MedAI',
  description: 'Secure patient health portal',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const isDemo = process.env.DEMO_MODE === 'true'

  return (
    <html lang="en">
      <body>
        {isDemo && (
          <div
            style={{
              background: '#f59e0b',
              color: '#1c1917',
              padding: '10px 24px',
              textAlign: 'center',
              fontWeight: 700,
              fontSize: '13px',
              letterSpacing: '0.01em',
              position: 'sticky',
              top: 0,
              zIndex: 9999,
              borderBottom: '2px solid #d97706',
            }}
          >
            ⚠ DEMO MODE — AI responses are pre-scripted. No LLM/Ollama required.&nbsp;&nbsp;|&nbsp;&nbsp;
            To enable real AI: stop this stack and run <code style={{ fontFamily: 'monospace', background: '#fde68a', padding: '1px 5px', borderRadius: '3px' }}>make start</code>
          </div>
        )}
        <div className="min-h-screen bg-slate-50">{children}</div>
      </body>
    </html>
  )
}
