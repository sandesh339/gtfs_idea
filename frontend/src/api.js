const BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'
const TOKEN = import.meta.env.VITE_REVIEWER_TOKEN || ''

function headers() {
  const h = { 'Content-Type': 'application/json' }
  if (TOKEN) h['X-Reviewer-Token'] = TOKEN
  return h
}

async function req(path, opts = {}) {
  const res = await fetch(`${BASE}${path}`, { headers: headers(), ...opts })
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}))
    throw new Error(detail.detail || `${res.status} ${res.statusText}`)
  }
  return res.json()
}

export const api = {
  health: () => req('/health'),

  newSession: () => req('/api/session?source=demo', { method: 'POST' }),

  uploadSession: async (file) => {
    const form = new FormData()
    form.append('file', file)
    const h = TOKEN ? { 'X-Reviewer-Token': TOKEN } : {}
    const res = await fetch(`${BASE}/api/session/upload`, { method: 'POST', headers: h, body: form })
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText)
    return res.json()
  },

  // Smart upload: browser -> Supabase directly (bypassing the backend for the
  // bytes) when available; otherwise fall back to streaming through the backend.
  upload: async (file, onStatus = () => {}) => {
    let sign
    try {
      onStatus('Preparing direct upload…')
      sign = await req('/api/upload/sign', { method: 'POST', body: JSON.stringify({ filename: file.name }) })
    } catch {
      onStatus('Uploading through the server…')       // direct upload unavailable (e.g. local disk backend)
      return api.uploadSession(file)
    }
    onStatus('Uploading directly to storage…')
    const put = await fetch(sign.url, {
      method: 'PUT',
      headers: { 'content-type': file.type || 'application/zip', 'x-upsert': 'true' },
      body: file,
    })
    if (!put.ok) throw new Error(`direct upload failed (${put.status})`)
    onStatus('Loading the feed…')
    return req('/api/session/from-upload', { method: 'POST', body: JSON.stringify({ path: sign.path }) })
  },

  chat: (sid, message) =>
    req(`/api/session/${sid}/chat`, { method: 'POST', body: JSON.stringify({ message }) }),

  codegenCommit: (sid, feed) =>
    req(`/api/session/${sid}/codegen/commit`, { method: 'POST', body: JSON.stringify({ feed }) }),

  codegenRepair: (sid, error) =>
    req(`/api/session/${sid}/codegen/repair`, { method: 'POST', body: JSON.stringify({ error }) }),

  undo: (sid) => req(`/api/session/${sid}/undo`, { method: 'POST' }),

  feed: (sid) => req(`/api/session/${sid}/feed`),

  exists: (sid) => req(`/api/session/${sid}/exists`),

  table: (sid, name, offset = 0, limit = 500) =>
    req(`/api/session/${sid}/table/${encodeURIComponent(name)}?offset=${offset}&limit=${limit}`),

  validate: (sid) => req(`/api/session/${sid}/validate`),

  diff: (sid) => req(`/api/session/${sid}/diff`),

  downloadUrl: (sid, scope = 'full') =>
    `${BASE}/api/session/${sid}/download?scope=${scope}` + (TOKEN ? '' : ''),

  // download needs the token header, so fetch as blob and trigger a save
  download: async (sid, scope = 'full') => {
    const res = await fetch(`${BASE}/api/session/${sid}/download?scope=${scope}`, { headers: headers() })
    if (!res.ok) throw new Error('download failed')
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `gtfs-${scope}.zip`
    a.click()
    URL.revokeObjectURL(url)
  },
}
