interface StatusPillProps {
  status: 'ok' | 'error' | 'loading' | 'idle'
  label?: string
}

export default function StatusPill({ status, label }: StatusPillProps) {
  const statusClass = {
    ok: 'status-ok',
    error: 'status-error',
    loading: 'status-loading',
    idle: 'status-idle',
  }[status]

  const defaultLabel = {
    ok: 'Healthy',
    error: 'Error',
    loading: 'Loading...',
    idle: 'Unknown',
  }[status]

  return (
    <span className={`status-pill ${statusClass}`}>
      {label || defaultLabel}
    </span>
  )
}
