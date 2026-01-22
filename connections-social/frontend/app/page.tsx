'use client'

import { useState, useEffect, useRef } from 'react'
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
  known_persons_total: number
  unknown_persons_total: number
  edges_total: number
  edges_known_only_total: number
  top_edges: Array<{
    person_a: string
    person_b: string
    weight: number
    evidence: string[]
  }>
}

interface LastAction {
  name: string
  status: 'success' | 'error' | 'pending'
  duration?: number
  result?: string
}

type LoadingState = {
  health: boolean
  rebuild: boolean
  reset: boolean
  ingest: boolean
  summary: boolean
  upload: boolean
  createProfile: boolean
  runDemo: boolean
}

export default function Dashboard() {
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [summary, setSummary] = useState<SummaryResponse | null>(null)
  const [lastResponse, setLastResponse] = useState<unknown>(null)
  const [lastUpdated, setLastUpdated] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [includeUnknown, setIncludeUnknown] = useState(false)
  const [forceIngest, setForceIngest] = useState(false)
  const [lastAction, setLastAction] = useState<LastAction | null>(null)
  const [loading, setLoading] = useState<LoadingState>({
    health: false,
    rebuild: false,
    reset: false,
    ingest: false,
    summary: false,
    upload: false,
    createProfile: false,
    runDemo: false,
  })

  // Advanced admin options
  const [showAdminAdvanced, setShowAdminAdvanced] = useState(false)

  // Upload state
  const [uploadFiles, setUploadFiles] = useState<FileList | null>(null)
  const [uploadProgress, setUploadProgress] = useState<string[]>([])
  const uploadInputRef = useRef<HTMLInputElement>(null)

  // Create profile state
  const [profileName, setProfileName] = useState('')
  const [profileFiles, setProfileFiles] = useState<FileList | null>(null)
  const [profileConfirmation, setProfileConfirmation] = useState<{
    needed: boolean
    bestMatch?: { name: string; similarity: number }
    mode: 'new' | 'merge'
  } | null>(null)
  const profileInputRef = useRef<HTMLInputElement>(null)

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
    const res = await api.get<SummaryResponse>(
      `/graph/summary?include_unknown=${includeUnknown}`
    )
    if (!res.error) {
      setSummary(res.data)
    }
    setLoading((s) => ({ ...s, summary: false }))
    return res
  }

  // Auto-refresh helper
  const autoRefresh = async () => {
    await fetchHealth()
    await fetchSummary()
  }

  const handleRebuild = async () => {
    const startTime = Date.now()
    setLoading((s) => ({ ...s, rebuild: true }))
    setError(null)
    setLastAction({ name: 'Rebuild Profile Index', status: 'pending' })

    const res = await api.post('/admin/rebuild-profile-index')
    const duration = Date.now() - startTime
    setLastResponse(res.data || { error: res.error })

    if (res.error) {
      setError(res.error)
      setLastAction({ name: 'Rebuild Profile Index', status: 'error', duration, result: res.error })
    } else {
      const data = res.data as { persons_created?: number; profiles_inserted?: number }
      setLastAction({
        name: 'Rebuild Profile Index',
        status: 'success',
        duration,
        result: `${data.persons_created} persons, ${data.profiles_inserted} profiles`
      })
      await autoRefresh()
    }
    updateTimestamp()
    setLoading((s) => ({ ...s, rebuild: false }))
  }

  const handleReset = async () => {
    const startTime = Date.now()
    setLoading((s) => ({ ...s, reset: true }))
    setError(null)
    setLastAction({ name: 'Reset Demo', status: 'pending' })

    const res = await api.post('/admin/reset-demo')
    const duration = Date.now() - startTime
    setLastResponse(res.data || { error: res.error })

    if (res.error) {
      setError(res.error)
      setLastAction({ name: 'Reset Demo', status: 'error', duration, result: res.error })
    } else {
      setLastAction({ name: 'Reset Demo', status: 'success', duration, result: 'Graph cleared' })
      await autoRefresh()
    }
    updateTimestamp()
    setLoading((s) => ({ ...s, reset: false }))
  }

  const handleIngest = async () => {
    const startTime = Date.now()
    setLoading((s) => ({ ...s, ingest: true }))
    setError(null)
    setLastAction({ name: 'Ingest Folder', status: 'pending' })

    const endpoint = forceIngest ? '/ingest/folder?force=true' : '/ingest/folder'
    const res = await api.post(endpoint)
    const duration = Date.now() - startTime
    setLastResponse(res.data || { error: res.error })

    if (res.error) {
      setError(res.error)
      setLastAction({ name: 'Ingest Folder', status: 'error', duration, result: res.error })
    } else {
      const data = res.data as { processed?: number; total_edges_created?: number }
      setLastAction({
        name: 'Ingest Folder',
        status: 'success',
        duration,
        result: `${data.processed} images, ${data.total_edges_created} edges`
      })
      await autoRefresh()
    }
    updateTimestamp()
    setLoading((s) => ({ ...s, ingest: false }))
  }

  const handleRunDemo = async () => {
    const startTime = Date.now()
    setLoading((s) => ({ ...s, runDemo: true }))
    setError(null)
    setLastAction({ name: 'Run Demo', status: 'pending' })

    // Step 1: Reset
    const resetRes = await api.post('/admin/reset-demo')
    if (resetRes.error) {
      const duration = Date.now() - startTime
      setError(resetRes.error)
      setLastResponse({ error: resetRes.error })
      setLastAction({ name: 'Run Demo', status: 'error', duration, result: `Reset failed: ${resetRes.error}` })
      setLoading((s) => ({ ...s, runDemo: false }))
      return
    }

    // Step 2: Ingest
    const ingestRes = await api.post('/ingest/folder')
    const duration = Date.now() - startTime
    setLastResponse(ingestRes.data || { error: ingestRes.error })

    if (ingestRes.error) {
      setError(ingestRes.error)
      setLastAction({ name: 'Run Demo', status: 'error', duration, result: `Ingest failed: ${ingestRes.error}` })
    } else {
      const data = ingestRes.data as { processed?: number; total_edges_created?: number }
      setLastAction({
        name: 'Run Demo',
        status: 'success',
        duration,
        result: `Reset + Ingested ${data.processed} images, ${data.total_edges_created} edges`
      })
      await autoRefresh()
    }
    updateTimestamp()
    setLoading((s) => ({ ...s, runDemo: false }))
  }

  const handleUpload = async () => {
    if (!uploadFiles || uploadFiles.length === 0) return

    const startTime = Date.now()
    setLoading((s) => ({ ...s, upload: true }))
    setError(null)
    setUploadProgress([])
    setLastAction({ name: 'Upload Photos', status: 'pending' })

    let totalEdges = 0
    let successCount = 0
    const progress: string[] = []

    for (let i = 0; i < uploadFiles.length; i++) {
      const file = uploadFiles[i]
      const formData = new FormData()
      formData.append('image', file)

      progress.push(`Uploading ${file.name}...`)
      setUploadProgress([...progress])

      try {
        const res = await fetch('/api/ingest/upload', {
          method: 'POST',
          body: formData,
        })
        const data = await res.json()

        if (res.ok) {
          progress[i] = `✓ ${file.name}: ${data.faces_detected} faces, ${data.edges_created} edges`
          totalEdges += data.edges_created || 0
          successCount++
        } else {
          progress[i] = `✗ ${file.name}: ${data.detail || 'Error'}`
        }
      } catch (e) {
        progress[i] = `✗ ${file.name}: Network error`
      }
      setUploadProgress([...progress])
    }

    const duration = Date.now() - startTime
    setLastAction({
      name: 'Upload Photos',
      status: successCount > 0 ? 'success' : 'error',
      duration,
      result: `${successCount}/${uploadFiles.length} uploaded, ${totalEdges} edges`
    })

    setUploadFiles(null)
    if (uploadInputRef.current) uploadInputRef.current.value = ''
    await autoRefresh()
    setLoading((s) => ({ ...s, upload: false }))
  }

  const handleCreateProfile = async (confirm = false, mode: 'new' | 'merge' = 'new') => {
    if (!profileName.trim() || !profileFiles || profileFiles.length === 0) {
      setError('Please enter a name and select 1-5 images')
      return
    }

    const startTime = Date.now()
    setLoading((s) => ({ ...s, createProfile: true }))
    setError(null)
    setLastAction({ name: 'Create Profile', status: 'pending' })

    const formData = new FormData()
    formData.append('name', profileName.trim())
    formData.append('confirm', String(confirm))
    formData.append('mode', mode)
    for (let i = 0; i < profileFiles.length; i++) {
      formData.append('images', profileFiles[i])
    }

    try {
      const res = await fetch('/api/profiles/create', {
        method: 'POST',
        body: formData,
      })
      const data = await res.json()
      setLastResponse(data)

      const duration = Date.now() - startTime

      if (data.status === 'confirmation_required') {
        setProfileConfirmation({
          needed: true,
          bestMatch: data.best_match,
          mode: 'new'
        })
        setLastAction({
          name: 'Create Profile',
          status: 'pending',
          duration,
          result: `Match found: ${data.best_match.name} (${(data.best_match.similarity * 100).toFixed(1)}%)`
        })
      } else if (data.status === 'completed') {
        setProfileConfirmation(null)
        setProfileName('')
        setProfileFiles(null)
        if (profileInputRef.current) profileInputRef.current.value = ''
        setLastAction({
          name: 'Create Profile',
          status: 'success',
          duration,
          result: `${data.person_name}: ${data.embeddings_added} embeddings added`
        })
        await autoRefresh()
      } else {
        setError(data.detail || 'Profile creation failed')
        setLastAction({ name: 'Create Profile', status: 'error', duration, result: data.detail })
      }
    } catch (e) {
      setLastAction({ name: 'Create Profile', status: 'error', result: 'Network error' })
      setError('Network error')
    }

    setLoading((s) => ({ ...s, createProfile: false }))
  }

  // Fetch health and summary on mount
  useEffect(() => {
    fetchHealth()
    fetchSummary()
  }, [])

  // Re-fetch summary when includeUnknown changes
  useEffect(() => {
    if (summary) {
      fetchSummary()
    }
  }, [includeUnknown])

  const anyLoading = Object.values(loading).some(Boolean)

  return (
    <div>
      <h1 className="page-title">Dashboard</h1>

      {error && <div className="error-message">{error}</div>}

      {/* Last Action Status */}
      {lastAction && (
        <div className={`last-action ${lastAction.status}`}>
          <div className="last-action-header">
            <span className="last-action-name">{lastAction.name}</span>
            <StatusPill
              status={lastAction.status === 'success' ? 'ok' : lastAction.status === 'error' ? 'error' : 'loading'}
              label={lastAction.status === 'pending' ? 'Running...' : lastAction.status}
            />
          </div>
          {lastAction.result && <div className="last-action-result">{lastAction.result}</div>}
          {lastAction.duration && <div className="last-action-duration">{(lastAction.duration / 1000).toFixed(1)}s</div>}
        </div>
      )}

      <div className="grid-2">
        {/* Health Card */}
        <div className="card">
          <div className="card-header">
            <span className="card-title">System Health</span>
            <StatusPill
              status={
                loading.health ? 'loading' : health?.status === 'healthy' ? 'ok' : health ? 'error' : 'idle'
              }
              label={
                loading.health ? 'Checking...' : health?.status === 'healthy' ? 'Healthy' : health ? 'Unhealthy' : 'Unknown'
              }
            />
          </div>
          <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
            Database: {health?.database || '—'}
            {lastUpdated && <span className="timestamp" style={{ marginLeft: '1rem' }}>Updated: {lastUpdated}</span>}
          </p>
        </div>

        {/* Graph Summary Card */}
        <div className="card">
          <div className="card-header">
            <span className="card-title">Graph Summary</span>
            {loading.summary && <span className="spinner" />}
          </div>
          {summary ? (
            <>
              <div className="stats-row">
                <div className="stat-item">
                  <div className="stat-value">{summary.known_persons_total}</div>
                  <div className="stat-label">Known Persons</div>
                </div>
                <div className="stat-item">
                  <div className="stat-value">{summary.unknown_persons_total}</div>
                  <div className="stat-label">Unknown Faces</div>
                </div>
                <div className="stat-item">
                  <div className="stat-value">{summary.edges_known_only_total}</div>
                  <div className="stat-label">Known Edges</div>
                </div>
              </div>
              {includeUnknown && (
                <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.5rem' }}>
                  Showing all: {summary.persons_total} persons, {summary.edges_total} edges
                </p>
              )}
            </>
          ) : (
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>Loading...</p>
          )}
        </div>
      </div>

      {/* Admin Actions */}
      <div className="card">
        <div className="card-title" style={{ marginBottom: '0.5rem' }}>Admin Actions</div>
        <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginBottom: '1rem' }}>
          Manage the system state. Click "Run Demo" to reset and ingest images.
        </p>

        {/* Primary Demo Action */}
        <div style={{ marginBottom: '1rem' }}>
          <button
            className="btn btn-primary"
            onClick={handleRunDemo}
            disabled={anyLoading}
            style={{ fontSize: '1rem', padding: '0.75rem 1.5rem' }}
          >
            {loading.runDemo && <span className="spinner" />}
            Run Demo
          </button>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginLeft: '0.75rem' }}>
            Resets graph and ingests all photos from uploads/
          </span>
        </div>

        {/* Advanced Admin Options (collapsible) */}
        <div style={{ borderTop: '1px solid var(--border)', paddingTop: '0.75rem' }}>
          <button
            type="button"
            onClick={() => setShowAdminAdvanced(!showAdminAdvanced)}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--text-secondary)',
              cursor: 'pointer',
              fontSize: '0.8rem',
              padding: 0,
              display: 'flex',
              alignItems: 'center',
              gap: '0.25rem'
            }}
          >
            <span style={{ transform: showAdminAdvanced ? 'rotate(90deg)' : 'none', transition: 'transform 0.2s' }}>
              ▶
            </span>
            Advanced Actions
          </button>
          {showAdminAdvanced && (
            <div style={{ marginTop: '0.75rem', paddingLeft: '1rem' }}>
              <div className="btn-group" style={{ marginBottom: '1rem' }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                  <button className="btn btn-primary" onClick={handleRebuild} disabled={anyLoading}>
                    {loading.rebuild && <span className="spinner" />}
                    Rebuild Profile Index
                  </button>
                  <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>
                    Rescans data/profiles. <strong>Destructive!</strong>
                  </span>
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                  <button className="btn btn-secondary" onClick={handleReset} disabled={anyLoading}>
                    {loading.reset && <span className="spinner" />}
                    Reset Demo
                  </button>
                  <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>
                    Clears graph only. Keeps profiles.
                  </span>
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                  <button className="btn btn-primary" onClick={handleIngest} disabled={anyLoading}>
                    {loading.ingest && <span className="spinner" />}
                    Ingest Photos
                  </button>
                  <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>
                    Processes images in uploads/.
                  </span>
                </div>
              </div>

              <div style={{ display: 'flex', gap: '2rem' }}>
                <div className="toggle-container">
                  <label className="toggle">
                    <input type="checkbox" checked={forceIngest} onChange={(e) => setForceIngest(e.target.checked)} />
                    <span className="toggle-slider" />
                  </label>
                  <span className="toggle-label">Force Ingest (Ignore history)</span>
                </div>
                <div className="toggle-container">
                  <label className="toggle">
                    <input type="checkbox" checked={includeUnknown} onChange={(e) => setIncludeUnknown(e.target.checked)} />
                    <span className="toggle-slider" />
                  </label>
                  <span className="toggle-label">Show Unknown Faces in Graph</span>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="grid-2">
        {/* Upload Photos */}
        <div className="card">
          <div className="card-title" style={{ marginBottom: '1rem' }}>Upload Group Photos</div>
          <input
            ref={uploadInputRef}
            type="file"
            multiple
            accept="image/*"
            onChange={(e) => setUploadFiles(e.target.files)}
            className="form-input"
            style={{ marginBottom: '0.5rem' }}
          />
          <button
            className="btn btn-primary"
            onClick={handleUpload}
            disabled={anyLoading || !uploadFiles || uploadFiles.length === 0}
            style={{ width: '100%' }}
          >
            {loading.upload && <span className="spinner" />}
            Upload {uploadFiles ? `(${uploadFiles.length} files)` : ''}
          </button>
          {uploadProgress.length > 0 && (
            <div className="upload-progress">
              {uploadProgress.map((p, i) => (
                <div key={i} className="upload-progress-item">{p}</div>
              ))}
            </div>
          )}
        </div>

        {/* Create Profile */}
        <div className="card">
          <div className="card-title" style={{ marginBottom: '1rem' }}>Create New Profile</div>
          <input
            type="text"
            placeholder="Person name"
            value={profileName}
            onChange={(e) => setProfileName(e.target.value)}
            className="form-input"
            style={{ marginBottom: '0.5rem' }}
          />
          <input
            ref={profileInputRef}
            type="file"
            multiple
            accept="image/*"
            onChange={(e) => setProfileFiles(e.target.files)}
            className="form-input"
            style={{ marginBottom: '0.5rem' }}
          />
          <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
            Upload 1-5 clear face photos of this person
          </p>
          {profileConfirmation?.needed ? (
            <div className="confirmation-box">
              <p>Potential match: <strong>{profileConfirmation.bestMatch?.name}</strong> ({(profileConfirmation.bestMatch?.similarity || 0) * 100}% similar)</p>
              <div className="btn-group" style={{ marginTop: '0.5rem' }}>
                <button className="btn btn-secondary" onClick={() => handleCreateProfile(true, 'merge')} disabled={anyLoading}>
                  Merge into {profileConfirmation.bestMatch?.name}
                </button>
                <button className="btn btn-primary" onClick={() => handleCreateProfile(true, 'new')} disabled={anyLoading}>
                  Create New Anyway
                </button>
                <button className="btn btn-secondary" onClick={() => setProfileConfirmation(null)}>
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <button
              className="btn btn-primary"
              onClick={() => handleCreateProfile(false)}
              disabled={anyLoading || !profileName.trim() || !profileFiles || profileFiles.length === 0}
              style={{ width: '100%' }}
            >
              {loading.createProfile && <span className="spinner" />}
              Create Profile
            </button>
          )}
        </div>
      </div>

      {/* Top Edges */}
      {summary && summary.top_edges && summary.top_edges.length > 0 && (
        <div className="card">
          <div className="card-title" style={{ marginBottom: '1rem' }}>Top Edges</div>
          <EdgesTable edges={summary.top_edges} title="" showEvidence />
        </div>
      )}

      {/* JSON Panel */}
      <JsonPanel data={lastResponse} />
    </div>
  )
}
