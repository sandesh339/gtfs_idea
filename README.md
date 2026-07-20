# GTFS editing chatbot + FC-vs-codegen benchmark

A GTFS feed-editing system with an intelligent **router** that dispatches each
request to **function calling** or **code generation**, plus a controlled
benchmark that maps where each mechanism wins. See `June26Meeting.pdf`.

## Status

- [x] Frozen function-calling tool library (`gtfs_tools/tools.py`, 20 ops)
- [x] In-memory feed model (`feed.py`), scope grammar (`scope.py`)
- [x] ReAct executor with matched repair rounds (`executor.py`)
- [x] Provider-agnostic LLM layer — GPT live (`llm.py`)
- [x] Oracle/grader: validity, correctness, integrity, damage, cost (`grader.py`)
- [x] Official MobilityData GTFS validator integration (`gtfs_validator.py`)
- [ ] Code-generation path (2nd mechanism)
- [ ] Router (predicts tool-fit / ambiguity)
- [ ] Expand scenarios 7 → 40; reconcile scenarios with the feed

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env            # then paste your OPENAI_API_KEY
```

Sample feed is in `data/sample-feed/` (Google GTFS demo feed).

Official validator (optional, for the `--official` validity dimension) needs
Java 11+ and the CLI jar:

```bash
# download once into vendor/ (jar is gitignored, ~38 MB)
curl -sL -o vendor/gtfs-validator-cli.jar \
  https://github.com/MobilityData/gtfs-validator/releases/download/v8.0.1/gtfs-validator-8.0.1-cli.jar
```

## Run

```bash
# one FC edit, print the call transcript
python run_fc.py "Rename the stop 'Stagecoach Hotel & Casino' to 'Stagecoach Casino'."

# run + grade a scenario (or all) on the five dimensions
python grade_fc.py R1
python grade_fc.py all
python grade_fc.py all --official        # use the official GTFS validator
python grade_fc.py all --no-llm          # re-grade saved out/<id> feeds, no API cost
```

## Web app (proof-of-concept chatbot)

Backend (FastAPI) + frontend (React/Vite). Two terminals:

```bash
# 1) backend  (reads OPENAI_API_KEY from .env)
uvicorn server.app:app --reload --port 8000

# 2) frontend
cd frontend
cp .env.example .env.local          # set VITE_API_BASE / VITE_REVIEWER_TOKEN
npm install
npm run dev                          # http://localhost:5173
```

The UI: chat panel (router decision badge + change summary + cost per turn) and a
tabbed workspace — **Map** (MapLibre, changed stops in red), **Tables**, **Diff** —
plus feed upload and full/changed-only zip download. Deploy targets: backend on
Render, frontend on Netlify, storage/sessions on Supabase (see below / memory).

### Code-gen execution: server (dev) vs browser (prod)

The backend env var `ALLOW_SERVER_CODEGEN` controls where code-gen runs:

- `ALLOW_SERVER_CODEGEN=1` (default, **local dev**) — code-gen runs on the
  server via the local subprocess runner. Convenient, but only safe locally.
- `ALLOW_SERVER_CODEGEN=0` (**production**) — `/chat` returns the generated
  program to the browser, which runs it in **Pyodide (WASM)** and drives the
  loop via `/codegen/commit` and `/codegen/repair`. Untrusted code never runs
  on the server. Set this in the Render deployment.

`GET /health` reports `"codegen": "server" | "client"` so you can confirm the mode.

### Session storage (survives Render spin-down)

Sessions persist to storage so they can be reconstructed after the free-tier
instance spins down (which wipes memory + local disk). Backend is chosen by env:

- No `SUPABASE_URL` → `LocalDiskStorage` under `sessions/` (dev default).
- `SUPABASE_URL` + a secret key → `SupabaseStorage` (a private bucket).

```
SUPABASE_URL=https://<ref>.supabase.co
SUPABASE_SERVICE_KEY=sb_secret_...     # or SUPABASE_KEY / SUPABASE_SECRET_KEY (backend only!)
SUPABASE_BUCKET=gtfs-session
# optional session cleanup (token-protected /cleanup, driven by an external cron):
CLEANUP_TOKEN=some-secret
```

`GET /health` reports the active `"storage"` backend. `POST /cleanup?hours=48`
(header `X-Cleanup-Token`) deletes idle sessions.

## Grading dimensions (per scenario)

| Dimension   | Meaning |
|-------------|---------|
| validity    | feed still valid (lightweight by default; official GTFS validator with `--official`, baseline-delta so pre-existing notices don't count) |
| correctness | the intended diff happened (per-scenario answer key) |
| integrity   | scenario invariants (sequence contiguity, monotonic times, refs) |
| damage      | nothing outside the sanctioned scope changed (entity-level diff) |
| cost        | tool calls / repair rounds (the boundary-map signal) |
