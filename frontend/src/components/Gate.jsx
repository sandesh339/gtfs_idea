import { useState } from 'react'

// Full-screen access-code prompt. Shown when the backend returns 401 (no/invalid
// reviewer token). On submit, the code is stored and the app retries.
export default function Gate({ error, onSubmit }) {
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e) {
    e.preventDefault()
    if (!code.trim() || busy) return
    setBusy(true)
    await onSubmit(code)
    setBusy(false)
  }

  return (
    <div className="gate">
      <form className="gate-card" onSubmit={submit}>
        <h1>GTFS Editing Chatbot</h1>
        <p>Enter the access code to continue.</p>
        <input
          type="password"
          autoFocus
          placeholder="Access code"
          value={code}
          onChange={(e) => setCode(e.target.value)}
        />
        {error && <div className="gate-error">{error}</div>}
        <button className="primary" type="submit" disabled={busy || !code.trim()}>
          {busy ? 'Checking…' : 'Enter'}
        </button>
      </form>
    </div>
  )
}
