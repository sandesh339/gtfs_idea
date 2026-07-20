"""FastAPI backend for the GTFS chatbot (Phase 1).

Wraps the ChatSession engine: create a session (demo feed or upload), chat,
undo, fetch the feed as JSON for the visualizer, and download the edited feed.

Local dev runs the code-gen path server-side (LocalSubprocessRunner). The
DEPLOYED app will run code-gen in the browser via Pyodide (see coderunner.py);
that protocol + the ALLOW_SERVER_CODEGEN gate land with the frontend in Phase 2.

Run:  uvicorn server.app:app --reload --port 8000
"""
from __future__ import annotations

import io
import os
import re
import uuid
import zipfile

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from gtfs_tools import Feed
from gtfs_tools.llm import OpenAIClient

from .auth import require_token
from .sessions import SessionStore
from .storage import (LocalDiskStorage, SupabaseStorage, feed_to_zip,
                      changed_tables, zip_bytes_to_feed)
from .validation import make_validator

load_dotenv(override=True)

DEMO_FEED_DIR = os.path.join("data", "sample-feed")

app = FastAPI(title="GTFS Chatbot API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in os.getenv("FRONTEND_ORIGIN", "*").split(",")],
    allow_methods=["*"], allow_headers=["*"],
)


def _client():
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise HTTPException(status_code=503, detail="server has no OPENAI_API_KEY configured")
    return OpenAIClient(model=os.getenv("OPENAI_MODEL", "gpt-5.5"), api_key=key,
                        base_url=os.getenv("OPENAI_BASE_URL"))


def _supabase_key():
    for name in ("SUPABASE_KEY", "SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_KEY"):
        val = os.getenv(name)
        if val:
            return val
    return None


def _build_storage():
    url, key = os.getenv("SUPABASE_URL"), _supabase_key()
    if url and key:
        return SupabaseStorage(url, key, os.getenv("SUPABASE_BUCKET", "gtfs-sessions"))
    return LocalDiskStorage(os.getenv("SESSION_ROOT", "sessions"))


storage = _build_storage()
validator = make_validator()
# one store; client built lazily so /health works without a key
_store: SessionStore | None = None


def store() -> SessionStore:
    global _store
    if _store is None:
        _store = SessionStore(_client(), storage)
    return _store


# True on local dev (safe to run code-gen here); set to 0 in production so the
# browser (Pyodide) runs code-gen instead of the server.
ALLOW_SERVER_CODEGEN = os.getenv("ALLOW_SERVER_CODEGEN", "1") == "1"


# ---- schemas ---------------------------------------------------------------
class ChatIn(BaseModel):
    message: str


class CommitIn(BaseModel):
    feed: dict            # {"tables": {name: {"headers": [...], "rows": [...]}}}


class RepairIn(BaseModel):
    error: str


class SignIn(BaseModel):
    filename: str = "feed.zip"


class FromUploadIn(BaseModel):
    path: str


def _safe_name(name: str) -> str:
    base = os.path.basename(name or "feed.zip")
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base)[:60] or "feed.zip"
    return base if base.endswith(".zip") else base + ".zip"


def feed_from_json(payload: dict) -> Feed:
    feed = Feed()
    for name, t in payload.get("tables", {}).items():
        feed.headers[name] = list(t.get("headers", []))
        feed.tables[name] = [dict(r) for r in t.get("rows", [])]
    return feed


# Big tables are excluded from the map/overview payload and loaded lazily/paged
# via /table. The map + diff + mini-maps only need stops/routes/trips/shapes.
HEAVY_TABLES = {"stop_times.txt"}


def feed_json(feed: Feed, light: bool = True) -> dict:
    tables, counts = {}, {}
    for name in sorted(feed.tables):
        counts[name] = len(feed.tables[name])
        if light and name in HEAVY_TABLES:
            continue
        tables[name] = {"headers": feed.headers.get(name, []), "rows": feed.tables[name]}
    return {"tables": tables, "counts": counts}


def serialize(resp) -> dict:
    d = resp.decision
    out = {
        "kind": resp.kind, "text": resp.text, "mechanism": resp.mechanism,
        "success": resp.success, "changes": resp.changes, "cost": resp.cost,
        "diff": resp.diff,
        "decision": None if d is None else {
            "tool_fit": d.tool_fit, "ambiguous": d.ambiguous, "confidence": d.confidence,
            "path": d.path, "reason": d.reason, "clarifying_question": d.clarifying_question},
    }
    if resp.kind == "codegen_client":
        out["program"] = resp.program
        out["repair_rounds"] = resp.repair_rounds
    return out


# ---- routes ----------------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok", "model": os.getenv("OPENAI_MODEL", "gpt-5.5"),
            "has_key": bool(os.getenv("OPENAI_API_KEY")),
            "codegen": "server" if ALLOW_SERVER_CODEGEN else "client",
            "storage": type(storage).__name__,
            "validator": type(validator).__name__}


@app.post("/cleanup")
def cleanup(hours: int = 48, x_cleanup_token: str = Header(default="")):
    """Delete sessions idle longer than `hours`. Protect with CLEANUP_TOKEN and
    trigger from an external cron. Disabled unless CLEANUP_TOKEN is set."""
    expected = os.getenv("CLEANUP_TOKEN", "")
    if not expected or x_cleanup_token != expected:
        raise HTTPException(status_code=403, detail="cleanup disabled or bad token")
    return {"removed": store().cleanup(hours * 3600)}


@app.post("/api/session", dependencies=[Depends(require_token)])
def new_session(source: str = "demo"):
    feed = Feed.load(DEMO_FEED_DIR)
    sid = store().create(feed)
    return {"session_id": sid, "feed_summary": _summary(feed), "label": "Demo feed"}


@app.post("/api/session/upload", dependencies=[Depends(require_token)])
async def upload_session(file: UploadFile = File(...)):
    data = await file.read()
    try:
        feed = zip_bytes_to_feed(data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"could not read GTFS zip: {e}")
    if "stops.txt" not in feed.tables or "routes.txt" not in feed.tables:
        raise HTTPException(status_code=400, detail="not a GTFS feed (missing stops/routes)")
    sid = store().create(feed)
    return {"session_id": sid, "feed_summary": _summary(feed),
            "label": _feed_label(feed, file.filename)}


@app.post("/api/upload/sign", dependencies=[Depends(require_token)])
def upload_sign(body: SignIn):
    """Mint a signed URL the browser uploads the feed zip to directly."""
    if not isinstance(storage, SupabaseStorage):
        raise HTTPException(status_code=400, detail="direct upload not available on this backend")
    path = f"uploads/{uuid.uuid4().hex}/{_safe_name(body.filename)}"
    return storage.sign_upload(path)


@app.post("/api/session/from-upload", dependencies=[Depends(require_token)])
def session_from_upload(body: FromUploadIn):
    """Create a session from a feed the browser uploaded directly to storage."""
    if not isinstance(storage, SupabaseStorage):
        raise HTTPException(status_code=400, detail="direct upload not available")
    path = body.path
    if not path.startswith("uploads/") or ".." in path:
        raise HTTPException(status_code=400, detail="invalid upload path")
    try:
        data = storage.download_raw(path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"could not read the upload: {e}")
    try:
        feed = zip_bytes_to_feed(data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"could not read GTFS zip: {e}")
    if "stops.txt" not in feed.tables or "routes.txt" not in feed.tables:
        raise HTTPException(status_code=400, detail="not a GTFS feed (missing stops/routes)")
    sid = store().create(feed)
    try:
        storage.remove_raw(path)          # drop the temp upload
    except Exception:
        pass
    return {"session_id": sid, "feed_summary": _summary(feed),
            "label": _feed_label(feed, os.path.basename(path))}


@app.post("/api/session/{sid}/chat", dependencies=[Depends(require_token)])
def chat(sid: str, body: ChatIn):
    session = store().get(sid)
    if session is None:
        raise HTTPException(status_code=404, detail="unknown or expired session")
    resp = session.handle(body.message, allow_server_codegen=ALLOW_SERVER_CODEGEN)
    if resp.kind != "codegen_client":   # no edit applied yet for client code-gen
        store().persist(sid)
    return serialize(resp)


@app.post("/api/session/{sid}/codegen/commit", dependencies=[Depends(require_token)])
def codegen_commit(sid: str, body: CommitIn):
    """Receive the feed the browser produced, validate, and commit if clean."""
    session = store().get(sid)
    if session is None:
        raise HTTPException(status_code=404, detail="unknown or expired session")
    resp = session.codegen_commit(feed_from_json(body.feed))
    if resp.success:
        store().persist(sid)
    return serialize(resp)


@app.post("/api/session/{sid}/codegen/repair", dependencies=[Depends(require_token)])
def codegen_repair(sid: str, body: RepairIn):
    """Generate a corrected program from the browser's error; returns the next
    program or exhausted=true when the repair budget runs out."""
    session = store().get(sid)
    if session is None:
        raise HTTPException(status_code=404, detail="unknown or expired session")
    out = session.codegen_repair(body.error)
    if out is None:
        return {"exhausted": True}
    program, rounds_left = out
    return {"exhausted": False, "program": program, "rounds_left": rounds_left}


@app.post("/api/session/{sid}/undo", dependencies=[Depends(require_token)])
def undo(sid: str):
    session = store().get(sid)
    if session is None:
        raise HTTPException(status_code=404, detail="unknown or expired session")
    ok = session.undo()
    store().persist(sid)
    return {"undone": ok, "changes": session.pending_changes()}


@app.get("/api/session/{sid}/diff", dependencies=[Depends(require_token)])
def get_diff(sid: str):
    """Cumulative rich diff of the current feed vs the originally loaded feed."""
    session = store().get(sid)
    if session is None:
        raise HTTPException(status_code=404, detail="unknown or expired session")
    from gtfs_tools.diffing import structured_diff, summarize_changes
    return {"diff": structured_diff(session.original, session.feed),
            "changes": summarize_changes(session.original, session.feed)}


@app.get("/api/session/{sid}/validate", dependencies=[Depends(require_token)])
def validate_feed_endpoint(sid: str):
    session = store().get(sid)
    if session is None:
        raise HTTPException(status_code=404, detail="unknown or expired session")
    try:
        return validator.validate(session.feed)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"validation failed: {e}")


@app.get("/api/session/{sid}/feed", dependencies=[Depends(require_token)])
def get_feed(sid: str):
    session = store().get(sid)
    if session is None:
        raise HTTPException(status_code=404, detail="unknown or expired session")
    return feed_json(session.feed, light=True)


@app.get("/api/session/{sid}/table/{name}", dependencies=[Depends(require_token)])
def get_table(sid: str, name: str, offset: int = 0, limit: int = 500):
    """A page of one table's rows (for the Tables tab; keeps big tables off /feed)."""
    session = store().get(sid)
    if session is None:
        raise HTTPException(status_code=404, detail="unknown or expired session")
    rows = session.feed.tables.get(name, [])
    limit = max(1, min(limit, 2000))
    return {"name": name, "headers": session.feed.headers.get(name, []),
            "rows": rows[offset:offset + limit], "total": len(rows), "offset": offset}


@app.get("/api/session/{sid}/exists", dependencies=[Depends(require_token)])
def session_exists(sid: str):
    """Cheap check for resume-on-reload — no feed download, no reconstruction."""
    return {"exists": storage.exists(sid)}


@app.get("/api/session/{sid}/download", dependencies=[Depends(require_token)])
def download(sid: str, scope: str = "full"):
    session = store().get(sid)
    if session is None:
        raise HTTPException(status_code=404, detail="unknown or expired session")
    only = None
    if scope == "changed":
        only = changed_tables(session.original, session.feed) or list(session.feed.tables)
    data = feed_to_zip(session.feed, only_tables=only)
    return StreamingResponse(
        io.BytesIO(data), media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="gtfs-{scope}.zip"'})


# ---- helpers ---------------------------------------------------------------
def _summary(feed: Feed) -> str:
    from gtfs_tools.router import feed_metadata
    return feed_metadata(feed)


def _feed_label(feed: Feed, filename: str = "") -> str:
    if filename:
        base = filename.rsplit("/", 1)[-1].rsplit(".", 1)[0].strip()
        if base:
            return base[:40]
    agency = feed.tables.get("agency.txt", [])
    if agency and agency[0].get("agency_name"):
        return agency[0]["agency_name"][:40]
    return "Uploaded feed"
