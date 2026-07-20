import { useEffect, useRef, useState } from 'react'
import RouterBadge from './RouterBadge.jsx'
import TurnChanges from './TurnChanges.jsx'

function Assistant({ m, feed }) {
  if (m.kind === 'status') {
    return (
      <div className="msg system">
        <div className="bubble"><span className="spinner" /> {m.text}</div>
      </div>
    )
  }
  const hasDiff = m.diff && m.diff.records
  return (
    <div className="msg assistant">
      <span className="who">assistant</span>
      {m.decision && <RouterBadge decision={m.decision} />}
      <div className="bubble">
        {m.kind === 'clarify' ? m.text : (m.kind === 'failed' ? `⚠ ${m.text}` : m.text)}
        {/* rich inline changes view when available; else the plain summary lines */}
        {hasDiff ? <TurnChanges diff={m.diff} feed={feed} />
          : m.changes?.length > 0 && (
            <div className="changes">
              {m.changes.map((c, i) => <div className="line" key={i}>{c}</div>)}
            </div>
          )}
      </div>
      {m.cost && (m.cost.calls != null) && (
        <span className="cost">{m.mechanism} · {m.cost.calls} call(s){m.cost.repairs ? `, ${m.cost.repairs} repair(s)` : ''}</span>
      )}
    </div>
  )
}

export default function ChatPanel({ messages, onSend, busy, feed }) {
  const [text, setText] = useState('')
  const endRef = useRef(null)
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages, busy])

  function submit() {
    const t = text.trim()
    if (!t || busy) return
    setText('')
    onSend(t)
  }

  return (
    <>
      <div className="messages">
        {messages.map((m, i) =>
          m.role === 'user' ? (
            <div className="msg user" key={i}><span className="who">you</span><div className="bubble">{m.text}</div></div>
          ) : m.role === 'system' ? (
            <div className="msg system" key={i}><div className="bubble">{m.text}</div></div>
          ) : (
            <Assistant m={m} feed={feed} key={i} />
          )
        )}
        {busy && <div className="msg assistant"><span className="who">assistant</span><div className="bubble"><span className="spinner" /> thinking…</div></div>}
        <div ref={endRef} />
      </div>
      <div className="composer">
        <textarea
          value={text}
          placeholder="Describe an edit, e.g. “Recolor the City route to 1E90FF”"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit() } }}
        />
        <button className="primary" onClick={submit} disabled={busy}>Send</button>
      </div>
    </>
  )
}
