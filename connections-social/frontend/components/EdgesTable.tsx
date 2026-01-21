interface Edge {
  person_a: string
  person_b: string
  weight: number
  evidence?: string[]
}

interface EdgesTableProps {
  edges: Edge[]
  title?: string
  onPersonClick?: (name: string) => void
}

export default function EdgesTable({ edges, title, onPersonClick }: EdgesTableProps) {
  if (!edges || edges.length === 0) {
    return (
      <div className="edges-table-empty">
        {title && <h4>{title}</h4>}
        <p>No edges to display</p>
      </div>
    )
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
            {edges[0]?.evidence && <th>Evidence</th>}
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
              {edge.evidence && (
                <td className="evidence-cell">
                  {edge.evidence.slice(0, 2).join(', ')}
                  {edge.evidence.length > 2 && ` +${edge.evidence.length - 2}`}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
