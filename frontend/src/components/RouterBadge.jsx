const LABELS = {
  fc: 'function calling',
  codegen: 'code generation',
  'fc->codegen': 'FC → code-gen',
  clarify: 'clarify',
}

export default function RouterBadge({ decision }) {
  if (!decision) return null
  const cls = decision.ambiguous ? 'clarify' : decision.tool_fit
  return (
    <div>
      <span className={`badge ${cls}`}>
        {LABELS[decision.path] || decision.path}
        <span className="conf">{Math.round(decision.confidence * 100)}%</span>
      </span>
      {decision.reason && <div className="reason">{decision.reason}</div>}
    </div>
  )
}
