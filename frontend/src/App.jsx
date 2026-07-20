import { useEffect, useRef, useState } from 'react'
import { api } from './api.js'
import { runCodegen } from './lib/pyodideRunner.js'
import ChatPanel from './components/ChatPanel.jsx'
import MapView from './components/MapView.jsx'
import TableView from './components/TableView.jsx'
import DiffView from './components/DiffView.jsx'
import ValidationView from './components/ValidationView.jsx'

const TABS = ['map', 'tables', 'diff', 'validation']
const WS_KEY = 'gtfs-ws'          // localStorage: { feeds, activeSid, chats }

function compactSummary(feed) {
  if (!feed) return ''
  const n = (t) => feed.counts?.[t] ?? feed.tables?.[t]?.rows.length ?? 0
  return `${n('routes.txt')} routes · ${n('stops.txt')} stops · ${n('trips.txt')} trips`
}

function stopsFromChanges(changes) {
  const ids = new Set()
  for (const c of changes || []) {
    const m = c.match(/\bstop\s+([A-Za-z0-9_\-]+)/)
    if (m) ids.add(m[1])
  }
  return ids
}

function lastChangesOf(messages) {
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].changes?.length) return messages[i].changes
  }
  return []
}

export default function App() {
  const [feeds, setFeeds] = useState([])          // [{sid, label}]  (the workspace)
  const [activeSid, setActiveSid] = useState(null)
  const [chats, setChats] = useState({})          // { sid: [msg, ...] }
  const [feed, setFeed] = useState(null)          // active feed tables
  const [busy, setBusy] = useState(false)
  const [tab, setTab] = useState('map')
  const [reports, setReports] = useState({})      // { sid: validation report }
  const [validating, setValidating] = useState(false)
  const [diffs, setDiffs] = useState({})          // { sid: cumulative diff }
  const [diffBusy, setDiffBusy] = useState(false)
  const [uploadStatus, setUploadStatus] = useState('')
  const fileRef = useRef(null)
  const loaded = useRef(false)
  const activeSidRef = useRef(null)
  useEffect(() => { activeSidRef.current = activeSid }, [activeSid])

  const messages = chats[activeSid] || []
  const lastChanges = lastChangesOf(messages)
  const changedStops = stopsFromChanges(lastChanges)

  // ---- persistence -----------------------------------------------------
  useEffect(() => { resume() }, [])
  useEffect(() => {
    if (!loaded.current) return
    localStorage.setItem(WS_KEY, JSON.stringify({ feeds, activeSid, chats }))
  }, [feeds, activeSid, chats])

  async function resume() {
    const saved = JSON.parse(localStorage.getItem(WS_KEY) || 'null')
    if (saved?.feeds?.length) {
      const alive = []
      for (const f of saved.feeds) {           // cheap existence check (no full download)
        try { const r = await api.exists(f.sid); if (r.exists) alive.push(f) } catch { /* gone */ }
      }
      if (alive.length) {
        const active = alive.some((f) => f.sid === saved.activeSid) ? saved.activeSid : alive[0].sid
        const keepChats = {}
        for (const f of alive) keepChats[f.sid] = saved.chats?.[f.sid] || []
        setFeeds(alive); setChats(keepChats); setActiveSid(active)
        setFeed(await api.feed(active))
        loaded.current = true
        return
      }
    }
    loaded.current = true
    await startDemo()
  }

  // ---- feed lifecycle --------------------------------------------------
  async function addFeed(sid, label, systemText) {
    const f = await api.feed(sid)
    setFeeds((prev) => (prev.some((x) => x.sid === sid) ? prev : [...prev, { sid, label }]))
    setChats((prev) => ({ ...prev, [sid]: prev[sid] || (systemText ? [{ role: 'system', text: systemText }] : []) }))
    setActiveSid(sid)
    setFeed(f)
  }

  async function startDemo() {
    try {
      const s = await api.newSession()
      await addFeed(s.session_id, s.label || 'Demo feed',
        `New session on the demo feed. Ask me to edit it.`)
    } catch (e) {
      setChats((c) => ({ ...c, __err: [{ role: 'system', text: `Could not reach the backend: ${e.message}` }] }))
      setActiveSid('__err')
    }
  }

  async function onUpload(e) {
    const file = e.target.files?.[0]
    if (!file) return
    setBusy(true)
    try {
      const s = await api.upload(file, setUploadStatus)
      await addFeed(s.session_id, s.label || file.name.replace(/\.zip$/i, ''),
        `Loaded “${s.label}” — ${s.feed_summary}.`)
    } catch (err) {
      alert(`Upload failed: ${err.message}`)
    } finally {
      setBusy(false); setUploadStatus(''); e.target.value = ''
    }
  }

  async function switchFeed(sid) {
    if (sid === activeSid) return
    setActiveSid(sid)
    setFeed(null)
    try {
      const f = await api.feed(sid)
      if (activeSidRef.current === sid) setFeed(f)
    } catch { /* handled elsewhere */ }
  }

  function closeFeed(sid, ev) {
    ev?.stopPropagation()
    const remaining = feeds.filter((f) => f.sid !== sid)
    setFeeds(remaining)
    setChats((prev) => { const { [sid]: _drop, ...rest } = prev; return rest })
    if (sid === activeSid) {
      if (remaining.length) switchFeed(remaining[0].sid)
      else startDemo()
    }
  }

  // ---- chat helpers ----------------------------------------------------
  const pushMsg = (sid, msg) => setChats((c) => ({ ...c, [sid]: [...(c[sid] || []), msg] }))

  function setStatus(sid, text) {
    setChats((c) => {
      const arr = c[sid] || []
      const trimmed = arr.length && arr[arr.length - 1].kind === 'status' ? arr.slice(0, -1) : arr
      return { ...c, [sid]: text ? [...trimmed, { role: 'assistant', kind: 'status', text }] : trimmed }
    })
  }

  async function reloadFeed(sid) {
    const f = await api.feed(sid)
    if (activeSidRef.current === sid) setFeed(f)
    // the report and cumulative diff are now outdated for this feed
    setReports((r) => { const { [sid]: _r, ...rest } = r; return rest })
    setDiffs((d) => { const { [sid]: _d, ...rest } = d; return rest })
  }

  async function runValidation(sid) {
    setValidating(true)
    try {
      const rep = await api.validate(sid)
      setReports((r) => ({ ...r, [sid]: rep }))
    } catch (e) {
      setReports((r) => ({ ...r, [sid]: { error: e.message } }))
    } finally {
      setValidating(false)
    }
  }

  async function loadDiff(sid) {
    setDiffBusy(true)
    try {
      const d = await api.diff(sid)
      setDiffs((prev) => ({ ...prev, [sid]: d }))
    } catch (e) {
      setDiffs((prev) => ({ ...prev, [sid]: { error: e.message } }))
    } finally {
      setDiffBusy(false)
    }
  }

  async function onSend(text) {
    const sid = activeSid
    pushMsg(sid, { role: 'user', text })
    setBusy(true)
    try {
      const r = await api.chat(sid, text)
      if (r.kind === 'codegen_client') {
        await runClientCodegen(sid, r)
      } else {
        pushMsg(sid, { role: 'assistant', ...r })
        if (r.success) { await reloadFeed(sid); if ((r.changes || []).some((c) => /stop/i.test(c))) setTab('map') }
      }
    } catch (e) {
      pushMsg(sid, { role: 'assistant', kind: 'failed', text: e.message })
    } finally {
      setBusy(false)
    }
  }

  async function runClientCodegen(sid, r) {
    pushMsg(sid, { role: 'assistant', kind: 'info', decision: r.decision,
      text: 'Generated a program — running it safely in your browser…' })
    let program = r.program
    let calls = 1, repairs = 0
    const snapshot = await api.feed(sid)          // program runs against this feed each attempt
    for (;;) {
      const exec = await runCodegen(program, snapshot, (t) => setStatus(sid, t))
      let error = null
      if (exec.ok) {
        const commit = await api.codegenCommit(sid, exec.feed)
        if (commit.success) {
          setStatus(sid, '')
          pushMsg(sid, { role: 'assistant', ...commit, cost: { calls, repairs }, mechanism: 'code generation (browser)' })
          await reloadFeed(sid); if ((commit.changes || []).some((c) => /stop/i.test(c))) setTab('map')
          return
        }
        error = commit.text
      } else {
        error = exec.error
      }
      const rep = await api.codegenRepair(sid, error)
      if (rep.exhausted) {
        setStatus(sid, '')
        pushMsg(sid, { role: 'assistant', kind: 'failed', text: 'Code generation could not produce a valid edit.\n\n' + error })
        return
      }
      program = rep.program; calls += 1; repairs += 1
      setStatus(sid, 'Repairing the program and re-running…')
    }
  }

  async function onUndo() {
    if (!activeSid) return
    const sid = activeSid
    setBusy(true)
    try {
      await api.undo(sid)
      await reloadFeed(sid)
      pushMsg(sid, { role: 'system', text: 'Reverted the last edit.' })
    } finally { setBusy(false) }
  }

  const canDownload = activeSid && activeSid !== '__err'

  return (
    <div className="app">
      <div className="topbar">
        <h1>GTFS Editing Chatbot</h1>
        <div className="feedbar">
          {feeds.map((f) => (
            <button key={f.sid} className={`feedchip ${f.sid === activeSid ? 'active' : ''}`}
              onClick={() => switchFeed(f.sid)} title={f.label}>
              <span className="feedchip-label">{f.label}</span>
              <span className="feedchip-close" onClick={(e) => closeFeed(f.sid, e)}>×</span>
            </button>
          ))}
        </div>
        <span className="meta">{uploadStatus ? <><span className="spinner" /> {uploadStatus}</> : (feed ? compactSummary(feed) : '')}</span>
        <div className="spacer" />
        <input ref={fileRef} type="file" accept=".zip" style={{ display: 'none' }} onChange={onUpload} />
        <button onClick={() => fileRef.current?.click()}>Upload feed</button>
        <button onClick={startDemo}>+ Demo</button>
        <button onClick={onUndo} disabled={!canDownload}>Undo</button>
        <button onClick={() => api.download(activeSid, 'changed')} disabled={!canDownload}>Download changed</button>
        <button className="primary" onClick={() => api.download(activeSid, 'full')} disabled={!canDownload}>Download feed</button>
      </div>

      <div className="main">
        <div className="chat-col">
          <ChatPanel messages={messages} onSend={onSend} busy={busy} feed={feed} />
        </div>
        <div className="work-col">
          <div className="tabs">
            {TABS.map((t) => (
              <button key={t} className={`tab ${tab === t ? 'active' : ''}`} onClick={() => setTab(t)}>
                {t[0].toUpperCase() + t.slice(1)}
              </button>
            ))}
          </div>
          <div className="tab-body">
            {tab === 'map' && <MapView feed={feed} changedStops={changedStops} />}
            {tab === 'tables' && <TableView feed={feed} sid={activeSid} />}
            {tab === 'diff' && canDownload && (
              <DiffView key={activeSid} data={diffs[activeSid]} feed={feed}
                busy={diffBusy} onLoad={() => loadDiff(activeSid)} />
            )}
            {tab === 'validation' && canDownload && (
              <ValidationView key={activeSid} report={reports[activeSid]}
                busy={validating} onRun={() => runValidation(activeSid)} />
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
