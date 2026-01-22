interface Edge {
  person_a: string
  person_b: string
  weight: number
  evidence?: string[]
  distance?: number
}

interface EdgesTableProps {
  edges: Edge[]
  title?: string
  onPersonClick?: (name: string) => void
  showEvidence?: boolean
  showDistance?: boolean
}

export default function EdgesTable({ edges, title, onPersonClick, showEvidence = false, showDistance = false }: EdgesTableProps) {
  if (!edges || edges.length === 0) {
    return (
      <div className="edges-table-empty">
        {title && <h4>{title}</h4>}
        <p>No edges to display</p>
      </div>
    )
  }

  const openImage = (filename: string) => {
    // Open image in new tab via the backend /images endpoint
    window.open(`http://localhost:8000/images/${filename}`, '_blank')
  }

  return (
    <div className="edges-table-container">
      {title && <h4>{title}</h4>}
      <table className="edges-table">
        <thead>
          <tr>
            <th>Person A</th>
            <th>Person B</th>
            <th>Weight</th>
            {showEvidence && edges[0]?.evidence && <th>Evidence</th>}
            {showDistance && <th>Distance</th>}
          </tr>
        </thead>
        <tbody>
          {edges.map((edge, i) => (
            <tr key={i}>
              <td>
                {onPersonClick ? (
                  <button
                    className="person-link"
                    onClick={() => onPersonClick(edge.person_a)}
                  >
                    {edge.person_a}
                  </button>
                ) : (
                  edge.person_a
                )}
              </td>
              <td>
                {onPersonClick ? (
                  <button
                    className="person-link"
                    onClick={() => onPersonClick(edge.person_b)}
                  >
                    {edge.person_b}
                  </button>
                ) : (
                  edge.person_b
                )}
              </td>
              <td>{edge.weight}</td>
              {showEvidence && edge.evidence && (
                <td className="evidence-cell">
                  {edge.evidence.slice(0, 3).map((filename, j) => (
                    <button
                      key={j}
                      className="evidence-link"
                      onClick={() => openImage(filename)}
                      title={filename}
                    >
                      {filename.length > 20 ? filename.slice(0, 17) + '...' : filename}
                    </button>
                  ))}
                  {edge.evidence.length > 3 && (
                    <span className="evidence-more">+{edge.evidence.length - 3} more</span>
                  )}
                </td>
              )}
              {showDistance && (
                <td className="distance-cell">
                  {edge.distance !== undefined ? edge.distance : '-'}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
