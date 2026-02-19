import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'Athlete Lookalike',
  description: 'Find out which NBA or NFL player you look like!',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body className="bg-gray-900 text-white min-h-screen">
        <nav className="bg-gray-800 border-b border-gray-700 px-6 py-4">
          <div className="max-w-6xl mx-auto flex items-center justify-between">
            <h1 className="text-2xl font-bold bg-gradient-to-r from-orange-500 to-red-500 bg-clip-text text-transparent">
              Athlete Lookalike
            </h1>
            <div className="flex gap-4 text-sm">
              <span className="px-3 py-1 bg-orange-600 rounded-full">NBA</span>
              <span className="px-3 py-1 bg-blue-600 rounded-full">NFL</span>
            </div>
          </div>
        </nav>
        <main className="max-w-6xl mx-auto px-6 py-8">
          {children}
        </main>
      </body>
    </html>
  )
}
