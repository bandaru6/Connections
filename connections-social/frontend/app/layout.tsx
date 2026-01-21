import type { Metadata } from 'next'
import TopNav from '@/components/TopNav'
import './globals.css'

export const metadata: Metadata = {
  title: 'Connections Social',
  description: 'Social graph from photos using face recognition',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body>
        <TopNav />
        <main className="main-container">
          {children}
        </main>
      </body>
    </html>
  )
}
