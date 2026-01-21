interface JsonPanelProps {
  title?: string
  data: unknown
}

export default function JsonPanel({ title = 'Last API Response', data }: JsonPanelProps) {
  return (
    <div className="json-panel">
      <div className="json-panel-header">{title}</div>
      <pre className="json-panel-content">
        {JSON.stringify(data, null, 2)}
      </pre>
    </div>
  )
}
