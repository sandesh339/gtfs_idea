export default function DiffPanel({ lastChanges }) {
  if (!lastChanges || lastChanges.length === 0) {
    return <div className="diff"><div className="empty">No edits yet. Ask the assistant to change something.</div></div>
  }
  return (
    <div className="diff">
      <h3>Most recent edit</h3>
      {lastChanges.map((c, i) => <div className="line" key={i}>{c}</div>)}
    </div>
  )
}
