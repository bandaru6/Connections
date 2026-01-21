'use client'

import { useState, useEffect } from 'react'
import { api } from '@/lib/apiFetch'
import StatusPill from '@/components/StatusPill'
import JsonPanel from '@/components/JsonPanel'
import EdgesTable from '@/components/EdgesTable'

interface HealthResponse {
  status: string
  database: string
}

interface SummaryResponse {
  persons_total: number
  edges_total: number
  top_edges: Array<{
    person_a: string
    person_b: string
    weight: number
    evidence: string[]
  }>
}

type LoadingState = {
  health: boolean
  rebuild: boolean
  reset: boolean
  ingest: boolean
  summary: boolean
}

export default function Dashboard() {
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [summary, setSummary] = useState<SummaryResponse | null>(null)
  const [lastResponse, setLastResponse] = useState<unknown>(null)
  const [lastUpdated, setLastUpdated] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [includeUnknown, setIncludeUnknown] = useState(false)
  const [forceIngest, setForceIngest] = useState(false)
  const [loading, setLoading] = useState<LoadingState>({
    health: false,
    rebuild: false,
    reset: false,
    ingest: false,
    summary: false,
  })

  const updateTimestamp = () => {
    setLastUpdated(new Date().toLocaleTimeString())
  }

  const fetchHealth = async () => {
    setLoading((s) => ({ ...s, health: true }))
    setError(null)
    const res = await api.get<HealthResponse>('/health')
    setLastResponse(res.data || { error: res.error })
    if (res.error) {
      setError(res.error)
      setHealth(null)
    } else {
      setHealth(res.data)
    }
    updateTimestamp()
    setLoading((s) => ({ ...s, health: false }))
  }

  const fetchSummary = async () => {
    setLoading((s) => ({ ...s, summary: true }))
    setError(null)
    const res = await api.get<SummaryResponse>(
      `/graph/summary?include_unknown=${includeUnknown}`
    )
    setLastResponse(res.data || { error: res.error })
    if (res.error) {
      setError(res.error)
    } else {
      setSummary(res.data)
    }
    updateTimestamp()
    setLoading((s) => ({ ...s, summary: false }))
  }

  const handleRebuild = async () => {
    setLoading((s) => ({ ...s, rebuild: true }))
    setError(null)
    const res = await api.post('/admin/rebuild-profile-index')
    setLastResponse(res.data || { error: res.error })
    if (res.error) {
      setError(res.error)
    }
    updateTimestamp()
    setLoading((s) => ({ ...s, rebuild: false }))
  }

  const handleReset = async () => {
    setLoading((s) => ({ ...s, reset: true }))
    setError(null)
    const res = await api.post('/admin/reset-demo')
    setLastResponse(res.data || { error: res.error })
    if (res.error) {
      setError(res.error)
    }
    updateTimestamp()
    setLoading((s) => ({ ...s, reset: false }))
  }

  const handleIngest = async () => {
    setLoading((s) => ({ ...s, ingest: true }))
    setError(null)
    const endpoint = forceIngest ? '/ingest/folder?force=true' : '/ingest/folder'
    const res = await api.post(endpoint)
    setLastResponse(res.data || { error: res.error })
    if (res.error) {
      setError(res.error)
    }
    updateTimestamp()
    setLoading((s) => ({ ...s, ingest: false }))
  }

  // Fetch health on mount
  useEffect(() => {
    fetchHealth()
  }, [])

  const anyLoading = Object.values(loading).some(Boolean)

  return (
    <div>
      <h1 className="page-title">Dashboard</h1>

      {error && <div className="error-message">{error}</div>}

      {/* Health Card */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">System Health</span>
          <StatusPill
            status={
              loading.health
                ? 'loading'
                : health?.status === 'healthy'
                ? 'ok'
                : health
                ? 'error'
                : 'idle'
            }
            label={
              loading.health
                ? 'Checking...'
                : health?.status === 'healthy'
                ? 'Healthy'
                : health
                ? 'Unhealthy'
                : 'Unknown'
            }
          />
        </div>
        <div>
          <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
            Database: {health?.database || '—'}
            {lastUpdated && (
              <span className="timestamp" style={{ marginLeft: '1rem' }}>
                Updated: {lastUpdated}
              </span>
            )}
          </p>
        </div>
      </div>

      {/* Demo Steps */}
      <div className="demo-steps">
        <div className="demo-steps-title">Demo Flow</div>
        <ol>
          <li>Click <strong>Rebuild Profile Index</strong> to index known faces</li>
          <li>Click <strong>Ingest Folder</strong> to process uploaded photos</li>
          <li>Click <strong>Refresh Summary</strong> to see the graph stats</li>
          <li>Go to <strong>Explore</strong> to query specific people</li>
        </ol>
      </div>

      {/* Action Buttons */}
      <div className="card">
        <div className="card-title" style={{ marginBottom: '1rem' }}>Actions</div>
        <div className="btn-group">
          <button
            className="btn btn-primary"
            onClick={handleRebuild}
            disabled={anyLoading}
          >
            {loading.rebuild && <span className="spinner" />}
            Rebuild Profile Index
          </button>
          <button
            className="btn btn-secondary"
            onClick={handleReset}
            disabled={anyLoading}
          >
            {loading.reset && <span className="spinner" />}
            Reset Demo
          </button>
          <button
            className="btn btn-primary"
            onClick={handleIngest}
            disabled={anyLoading}
          >
            {loading.ingest && <span className="spinner" />}
            Ingest Folder
          </button>
          <button
            className="btn btn-secondary"
            onClick={fetchSummary}
            disabled={anyLoading}
          >
            {loading.summary && <span className="spinner" />}
            Refresh Summary
          </button>
          <button
            className="btn btn-secondary"
            onClick={fetchHealth}
            disabled={anyLoading}
          >
            {loading.health && <span className="spinner" />}
            Check Health
          </button>
        </div>

        {/* Toggles */}
        <div style={{ display: 'flex', gap: '2rem', marginTop: '0.5rem' }}>
          <div className="toggle-container">
            <label className="toggle">
              <input
                type="checkbox"
                checked={forceIngest}
                onChange={(e) => setForceIngest(e.target.checked)}
              />
              <span className="toggle-slider" />
            </label>
            <span className="toggle-label">Force Ingest</span>
          </div>
          <div className="toggle-container">
            <label className="toggle">
              <input
                type="checkbox"
                checked={includeUnknown}
                onChange={(e) => setIncludeUnknown(e.target.checked)}
              />
              <span className="toggle-slider" />
            </label>
            <span className="toggle-label">Include Unknown</span>
          </div>
        </div>
      </div>

      {/* Graph Summary */}
      <div className="card">
        <div className="card-title" style={{ marginBottom: '1rem' }}>
          Graph Summary
        </div>
        {summary ? (
          <>
            <div className="stats-row">
              <div className="stat-item">
                <div className="stat-value">{summary.persons_total}</div>
                <div className="stat-label">Persons</div>
              </div>
              <div className="stat-item">
                <div className="stat-value">{summary.edges_total}</div>
                <div className="stat-label">Edges</div>
              </div>
            </div>
            <EdgesTable edges={summary.top_edges} title="Top Edges" />
          </>
        ) : (
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
            Click &quot;Refresh Summary&quot; to load graph statistics
          </p>
        )}
      </div>

      {/* JSON Panel */}
      <JsonPanel data={lastResponse} />
    </div>
  )
}
