'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'

export default function TopNav() {
  const pathname = usePathname()

  const links = [
    { href: '/', label: 'Dashboard' },
    { href: '/explore', label: 'Explore' },
  ]

  return (
    <nav className="top-nav">
      <div className="nav-brand">Connections Social</div>
      <div className="nav-links">
        {links.map((link) => (
          <Link
            key={link.href}
            href={link.href}
            className={`nav-link ${pathname === link.href ? 'active' : ''}`}
          >
            {link.label}
          </Link>
        ))}
      </div>
    </nav>
  )
}
