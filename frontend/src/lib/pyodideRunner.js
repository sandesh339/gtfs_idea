// Runs a model-generated Python program IN THE BROWSER via Pyodide (WASM).
// The untrusted code executes in the WASM sandbox — it cannot reach the server,
// its keys, or other users' data. pandas is loaded so generated pandas code runs.

const PYODIDE_VERSION = 'v0.26.4'
const INDEX_URL = `https://cdn.jsdelivr.net/pyodide/${PYODIDE_VERSION}/full/`

// Python harness: write the feed to CSV files, run the program in a fresh dir,
// read the files back. Mirrors the offline LocalSubprocessRunner semantics.
const HARNESS = `
import csv, os, json, tempfile, traceback

def _write_feed(feed):
    for name, t in feed['tables'].items():
        with open(name, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=t['headers'])
            w.writeheader()
            for row in t['rows']:
                w.writerow({h: ('' if row.get(h) is None else row.get(h, '')) for h in t['headers']})

def _read_feed():
    tables = {}
    for name in sorted(os.listdir('.')):
        if name.endswith('.txt'):
            with open(name, newline='', encoding='utf-8') as f:
                r = csv.DictReader(f, restval='')
                headers = list(r.fieldnames or [])
                rows = [{h: (row.get(h) or '') for h in headers} for row in r]
                tables[name] = {'headers': headers, 'rows': rows}
    return {'tables': tables}

def run_program(feed_json, program):
    feed = json.loads(feed_json)
    os.chdir(tempfile.mkdtemp())     # fresh dir each attempt
    _write_feed(feed)
    g = {'__name__': '__main__'}
    try:
        exec(program, g)
    except Exception:
        return json.dumps({'ok': False, 'error': traceback.format_exc()})
    return json.dumps({'ok': True, 'feed': _read_feed()})
`

let pyodidePromise = null

function loadScript(src) {
  return new Promise((resolve, reject) => {
    if (window.loadPyodide) return resolve()
    const s = document.createElement('script')
    s.src = src
    s.onload = resolve
    s.onerror = () => reject(new Error('failed to load Pyodide script'))
    document.head.appendChild(s)
  })
}

// Lazily boot Pyodide + pandas once. onStatus reports progress for the UI.
export async function ensurePyodide(onStatus = () => {}) {
  if (!pyodidePromise) {
    pyodidePromise = (async () => {
      onStatus('Loading the Python runtime (first time only, ~10–20s)…')
      await loadScript(`${INDEX_URL}pyodide.js`)
      const py = await window.loadPyodide({ indexURL: INDEX_URL })
      onStatus('Loading pandas…')
      await py.loadPackage('pandas')
      py.runPython(HARNESS)
      onStatus('')
      return py
    })().catch((e) => { pyodidePromise = null; throw e })
  }
  return pyodidePromise
}

// Run `program` against `feed` (our {tables:{name:{headers,rows}}} shape).
// Returns { ok: true, feed } or { ok: false, error }.
export async function runCodegen(program, feed, onStatus = () => {}) {
  const py = await ensurePyodide(onStatus)
  const fn = py.globals.get('run_program')
  try {
    const outStr = fn(JSON.stringify(feed), program)
    return JSON.parse(outStr)
  } catch (e) {
    return { ok: false, error: String(e) }
  } finally {
    fn.destroy?.()
  }
}
