'use client'

import { useState, useEffect } from 'react'
import { api } from '@/lib/apiFetch'
import JsonPanel from '@/components/JsonPanel'
import NeighborsList from '@/components/NeighborsList'
import EdgesTable from '@/components/EdgesTable'
import NetworkGraph from '@/components/NetworkGraph'

interface Neighbor {
  neighbor: string
  weight: number
  evidence?: string[]
}

interface NeighborsResponse {
  person: string
  neighbors: Neighbor[]
}

interface EgoNode {
  name: string
  is_unknown: boolean
}

interface EgoEdge {
  source: string
  target: string
  weight: number
}

interface EgoResponse {
  center: string
  depth: number
  nodes: EgoNode[]
  edges: EgoEdge[]
}

interface PathEdge {
  person_a: string
  person_b: string
  weight: number
  evidence: string[]
}

interface PathResponse {
  source: string
  target: string
  found: boolean
  path: string[]
  hops: number
  edges: PathEdge[]
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
    path: false,
  })

  // Path search state
  const [sourceName, setSourceName] = useState('')
  const [targetName, setTargetName] = useState('')
  const [pathResult, setPathResult] = useState<PathResponse | null>(null)
  
  // Person suggestions
  const [personSuggestions, setPersonSuggestions] = useState<string[]>([])

  useEffect(() => {
    // Fetch person list for autocomplete
    const fetchPersons = async () => {
      const res = await api.get<{ persons: string[] }>('/graph/persons/list?limit=500')
      if (!res.error && res.data) {
        setPersonSuggestions(res.data.persons)
      }
    }
    fetchPersons()
  }, [])

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

  const fetchPath = async () => {
    if (!sourceName.trim() || !targetName.trim()) {
      setError('Please enter both source and target names')
      return
    }

    setLoading((s) => ({ ...s, path: true }))
    setError(null)

    const params = new URLSearchParams({
      source: sourceName,
      target: targetName,
      include_unknown: String(includeUnknown),
    })

    const res = await api.get<PathResponse>(`/graph/path?${params}`)
    setLastResponse(res.data || { error: res.error })

    if (res.error) {
      setError(res.error)
      setPathResult(null)
    } else {
      setPathResult(res.data)
    }

    setLoading((s) => ({ ...s, path: false }))
  }

  const handleNeighborClick = (name: string) => {
    setPersonName(name)
    fetchNeighbors(name)
  }

  const handlePersonClick = (name: string) => {
    setPersonName(name)
  }

  const openImage = (filename: string) => {
    window.open(`http://localhost:8000/images/${filename}`, '_blank')
  }

  // Compute BFS distances from ego center
  const computeDistances = (center: string, edges: Array<{ source: string; target: string }>) => {
    const distances: Record<string, number> = { [center]: 0 }
    const queue: string[] = [center]
    const adjacency: Record<string, string[]> = {}

    // Build adjacency list
    for (const edge of edges) {
      if (!adjacency[edge.source]) adjacency[edge.source] = []
      if (!adjacency[edge.target]) adjacency[edge.target] = []
      adjacency[edge.source].push(edge.target)
      adjacency[edge.target].push(edge.source)
    }

    // BFS
    while (queue.length > 0) {
      const current = queue.shift()!
      const currentDist = distances[current]
      for (const neighbor of adjacency[current] || []) {
        if (distances[neighbor] === undefined) {
          distances[neighbor] = currentDist + 1
          queue.push(neighbor)
        }
      }
    }

    return distances
  }

  // Get edge distance (min of the two node distances)
  const getEdgeDistance = (distances: Record<string, number>, source: string, target: string) => {
    const d1 = distances[source]
    const d2 = distances[target]
    if (d1 === undefined && d2 === undefined) return undefined
    if (d1 === undefined) return d2
    if (d2 === undefined) return d1
    return Math.min(d1, d2)
  }

  const anyLoading = loading.neighbors || loading.ego || loading.path

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
              list="person-suggestions"
              onChange={(e) => setPersonName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') fetchNeighbors()
              }}
            />
            <datalist id="person-suggestions">
              {personSuggestions.map((name) => (
                <option key={name} value={name} />
              ))}
            </datalist>
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
            <span className="toggle-label">Include Unknown Faces</span>
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

      {/* Find Connection */}
      <div className="card">
        <div className="card-title" style={{ marginBottom: '1rem' }}>
          Find Connection
        </div>

        <div className="form-row">
          <div className="form-group" style={{ flex: 1, marginBottom: 0 }}>
            <label className="form-label">Source Person</label>
            <input
              type="text"
              className="form-input"
              placeholder="Joe Biden"
              value={sourceName}
              list="person-suggestions"
              onChange={(e) => setSourceName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') fetchPath()
              }}
            />
          </div>

          <div className="form-group" style={{ flex: 1, marginBottom: 0 }}>
            <label className="form-label">Target Person</label>
            <input
              type="text"
              className="form-input"
              placeholder="Kamala Harris"
              value={targetName}
              list="person-suggestions"
              onChange={(e) => setTargetName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') fetchPath()
              }}
            />
          </div>

          <button
            className="btn btn-primary"
            onClick={fetchPath}
            disabled={anyLoading}
            style={{ alignSelf: 'flex-end' }}
          >
            {loading.path && <span className="spinner" />}
            Find Shortest Path
          </button>
        </div>

        {/* Path Result */}
        {pathResult && (
          <div className="path-result" style={{ marginTop: '1rem' }}>
            {pathResult.found ? (
              <>
                <div className="path-summary" style={{ marginBottom: '0.75rem' }}>
                  <span style={{ fontSize: '0.875rem', color: 'var(--success)' }}>
                    Path found! {pathResult.hops} hop{pathResult.hops !== 1 ? 's' : ''}
                  </span>
                </div>
                <div className="path-chain" style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '0.5rem', marginBottom: '1rem' }}>
                  {pathResult.path.map((name, i) => (
                    <span key={i} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <button
                        className="person-link"
                        onClick={() => handlePersonClick(name)}
                        style={{ fontWeight: i === 0 || i === pathResult.path.length - 1 ? 600 : 400 }}
                      >
                        {name}
                      </button>
                      {i < pathResult.path.length - 1 && <span style={{ color: 'var(--text-secondary)' }}>→</span>}
                    </span>
                  ))}
                </div>
                <EdgesTable edges={pathResult.edges} title="Edges in Path" showEvidence />
              </>
            ) : (
              <div style={{ color: 'var(--warning)', fontSize: '0.875rem' }}>
                No path found between {pathResult.source} and {pathResult.target}
              </div>
            )}
          </div>
        )}
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
              {/* Graph Visualization */}
              <div style={{ marginBottom: '1rem' }}>
                <NetworkGraph
                  center={ego.center}
                  nodes={ego.nodes}
                  edges={ego.edges}
                  onNodeClick={handlePersonClick}
                />
                <p style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', marginTop: '0.25rem', textAlign: 'center' }}>
                  Click a node to select it
                </p>
              </div>
              {/* Node list */}
              <div className="ego-nodes" style={{ marginBottom: '1rem' }}>
                <h4 style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
                  Nodes
                </h4>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.25rem' }}>
                  {ego.nodes.map((node, i) => (
                    <button
                      key={i}
                      className={`person-link ${node.is_unknown ? 'unknown' : ''}`}
                      onClick={() => handlePersonClick(node.name)}
                      style={{
                        padding: '0.25rem 0.5rem',
                        fontSize: '0.75rem',
                        opacity: node.is_unknown ? 0.6 : 1
                      }}
                    >
                      {node.name}
                    </button>
                  ))}
                </div>
              </div>
              {/* Transform edges for EdgesTable with distances */}
              {(() => {
                const distances = computeDistances(ego.center, ego.edges)
                return (
                  <EdgesTable
                    edges={ego.edges.map(e => ({
                      person_a: e.source,
                      person_b: e.target,
                      weight: e.weight,
                      distance: getEdgeDistance(distances, e.source, e.target)
                    }))}
                    title="Edges"
                    onPersonClick={handlePersonClick}
                    showDistance
                  />
                )
              })()}
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
