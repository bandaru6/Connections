'use client'

import { useState } from 'react'
import { api } from '@/lib/apiFetch'
import JsonPanel from '@/components/JsonPanel'
import NeighborsList from '@/components/NeighborsList'
import EdgesTable from '@/components/EdgesTable'

interface Neighbor {
  person: string
  weight: number
}

interface NeighborsResponse {
  person: string
  neighbors: Neighbor[]
}

interface EgoEdge {
  person_a: string
  person_b: string
  weight: number
}

interface EgoResponse {
  center: string
  depth: number
  nodes: string[]
  edges: EgoEdge[]
}

export default function ExplorePage() {
  const [personName, setPersonName] = useState('')
  const [depth, setDepth] = useState(2)
  const [includeUnknown, setIncludeUnknown] = useState(false)
  const [neighbors, setNeighbors] = useState<NeighborsResponse | null>(null)
  const [ego, setEgo] = useState<EgoResponse | null>(null)
  const [lastResponse, setLastResponse] = useState<unknown>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState({
    neighbors: false,
    ego: false,
  })

  const fetchNeighbors = async (name?: string) => {
    const searchName = name || personName
    if (!searchName.trim()) {
      setError('Please enter a person name')
      return
    }

    setLoading((s) => ({ ...s, neighbors: true }))
    setError(null)

    const params = new URLSearchParams({
      person: searchName,
      include_unknown: String(includeUnknown),
    })

    const res = await api.get<NeighborsResponse>(`/graph/neighbors?${params}`)
    setLastResponse(res.data || { error: res.error })

    if (res.error) {
      setError(res.error)
      setNeighbors(null)
    } else {
      setNeighbors(res.data)
      if (name) setPersonName(name)
    }

    setLoading((s) => ({ ...s, neighbors: false }))
  }

  const fetchEgo = async () => {
    if (!personName.trim()) {
      setError('Please enter a person name')
      return
    }

    setLoading((s) => ({ ...s, ego: true }))
    setError(null)

    const params = new URLSearchParams({
      person: personName,
      depth: String(depth),
      include_unknown: String(includeUnknown),
    })

    const res = await api.get<EgoResponse>(`/graph/ego?${params}`)
    setLastResponse(res.data || { error: res.error })

    if (res.error) {
      setError(res.error)
      setEgo(null)
    } else {
      setEgo(res.data)
    }

    setLoading((s) => ({ ...s, ego: false }))
  }

  const handleNeighborClick = (name: string) => {
    setPersonName(name)
    fetchNeighbors(name)
  }

  const handlePersonClick = (name: string) => {
    setPersonName(name)
  }

  const anyLoading = loading.neighbors || loading.ego

  return (
    <div>
      <h1 className="page-title">Explore Graph</h1>

      {error && <div className="error-message">{error}</div>}

      {/* Search Controls */}
      <div className="card">
        <div className="card-title" style={{ marginBottom: '1rem' }}>
          Search Person
        </div>

        <div className="form-row">
          <div className="form-group" style={{ flex: 1, marginBottom: 0 }}>
            <label className="form-label">Person Name</label>
            <input
              type="text"
              className="form-input"
              placeholder="Barack Obama"
              value={personName}
              onChange={(e) => setPersonName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') fetchNeighbors()
              }}
            />
          </div>

          <div className="form-group" style={{ marginBottom: 0 }}>
            <label className="form-label">Depth</label>
            <select
              className="form-select"
              value={depth}
              onChange={(e) => setDepth(Number(e.target.value))}
            >
              <option value={1}>1</option>
              <option value={2}>2</option>
              <option value={3}>3</option>
            </select>
          </div>

          <div className="toggle-container" style={{ paddingBottom: '0.25rem' }}>
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

        <div className="btn-group" style={{ marginTop: '1rem' }}>
          <button
            className="btn btn-primary"
            onClick={() => fetchNeighbors()}
            disabled={anyLoading}
          >
            {loading.neighbors && <span className="spinner" />}
            Get Neighbors
          </button>
          <button
            className="btn btn-primary"
            onClick={fetchEgo}
            disabled={anyLoading}
          >
            {loading.ego && <span className="spinner" />}
            Get Ego Network
          </button>
        </div>
      </div>

      {/* Results Grid */}
      <div className="grid-2">
        {/* Neighbors */}
        <div className="card">
          <div className="card-title" style={{ marginBottom: '1rem' }}>
            {neighbors ? `Neighbors of ${neighbors.person}` : 'Neighbors'}
          </div>
          {neighbors ? (
            <NeighborsList
              neighbors={neighbors.neighbors}
              onNeighborClick={handleNeighborClick}
            />
          ) : (
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
              Enter a name and click &quot;Get Neighbors&quot;
            </p>
          )}
        </div>

        {/* Ego Network */}
        <div className="card">
          <div className="card-title" style={{ marginBottom: '1rem' }}>
            {ego ? `Ego Network (depth ${ego.depth})` : 'Ego Network'}
          </div>
          {ego ? (
            <>
              <div className="stats-row" style={{ marginBottom: '1rem' }}>
                <div className="stat-item">
                  <div className="stat-value">{ego.nodes.length}</div>
                  <div className="stat-label">Nodes</div>
                </div>
                <div className="stat-item">
                  <div className="stat-value">{ego.edges.length}</div>
                  <div className="stat-label">Edges</div>
                </div>
              </div>
              <EdgesTable
                edges={ego.edges}
                title="Edges"
                onPersonClick={handlePersonClick}
              />
            </>
          ) : (
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
              Enter a name and click &quot;Get Ego Network&quot;
            </p>
          )}
        </div>
      </div>

      {/* JSON Panel */}
      <JsonPanel data={lastResponse} />
    </div>
  )
}
