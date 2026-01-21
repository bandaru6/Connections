interface Neighbor {
  person: string
  weight: number
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

  return (
    <div className="neighbors-list">
      <h4>Neighbors ({neighbors.length})</h4>
      <ul>
        {sorted.map((neighbor, i) => (
          <li key={i} className="neighbor-item">
            {onNeighborClick ? (
              <button
                className="person-link"
                onClick={() => onNeighborClick(neighbor.person)}
              >
                {neighbor.person}
              </button>
            ) : (
              <span>{neighbor.person}</span>
            )}
            <span className="neighbor-weight">weight: {neighbor.weight}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
