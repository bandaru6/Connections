interface Neighbor {
  neighbor: string
  weight: number
  evidence?: string[]
}

interface NeighborsListProps {
  neighbors: Neighbor[]
  onNeighborClick?: (name: string) => void
}

export default function NeighborsList({ neighbors, onNeighborClick }: NeighborsListProps) {
  if (!neighbors || neighbors.length === 0) {
    return (
      <div className="neighbors-list-empty">
        <p>No neighbors found</p>
      </div>
    )
  }

  // Sort by weight descending
  const sorted = [...neighbors].sort((a, b) => b.weight - a.weight)

  const openImage = (filename: string) => {
    window.open(`http://localhost:8000/images/${filename}`, '_blank')
  }

  return (
    <div className="neighbors-list">
      <h4>Neighbors ({neighbors.length})</h4>
      <ul>
        {sorted.map((n, i) => {
           // Defensive check for name property
           const name = n.neighbor || (n as any).name || 'Unknown'
           return (
            <li key={i} className="neighbor-item">
              <div className="neighbor-info">
                {onNeighborClick ? (
                  <button
                    className="person-link"
                    onClick={() => onNeighborClick(name)}
                    style={{ textAlign: 'left' }}
                  >
                    {name}
                  </button>
                ) : (
                  <span className="neighbor-name">{name}</span>
                )}
                <span className="neighbor-weight">weight: {n.weight}</span>
              </div>
              {n.evidence && n.evidence.length > 0 && (
                <div className="neighbor-evidence">
                  {n.evidence.slice(0, 2).map((filename, j) => (
                    <button
                      key={j}
                      className="evidence-link"
                      onClick={() => openImage(filename)}
                      title={filename}
                    >
                      img
                    </button>
                  ))}
                  {n.evidence.length > 2 && (
                    <span className="evidence-more">+{n.evidence.length - 2}</span>
                  )}
                </div>
              )}
            </li>
          )
        })}
      </ul>
    </div>
  )
}
