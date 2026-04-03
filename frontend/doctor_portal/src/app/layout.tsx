import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'Doctor Dashboard | MedAI',
  description: 'Clinical decision support dashboard',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="min-h-screen bg-slate-100">{children}</div>
      </body>
    </html>
  )
}
