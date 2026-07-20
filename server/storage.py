"""Storage abstraction for session state (feeds + history/metadata).

Two backends implement the same interface:
  LocalDiskStorage  local dev — session dirs under <root>/<id>/
  SupabaseStorage   production — objects in a private Supabase bucket

Feeds persist so a session can be RECONSTRUCTED after a Render spin-down (which
wipes memory + local disk). Per session we keep: original feed, current feed,
and state.json (conversation history + timestamps). Undo is in-memory only.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import time
import zipfile
from abc import ABC, abstractmethod
from typing import List, Optional

from gtfs_tools import Feed


class Storage(ABC):
    @abstractmethod
    def save_feed(self, session_id: str, feed: Feed, which: str = "current") -> None: ...
    @abstractmethod
    def load_feed(self, session_id: str, which: str = "current") -> Feed: ...
    @abstractmethod
    def save_state(self, session_id: str, state: dict) -> None: ...
    @abstractmethod
    def load_state(self, session_id: str) -> Optional[dict]: ...
    @abstractmethod
    def exists(self, session_id: str) -> bool: ...
    @abstractmethod
    def delete(self, session_id: str) -> None: ...
    @abstractmethod
    def cleanup(self, max_age_seconds: int) -> int:
        """Delete sessions whose state.last_active is older than max_age. Returns count."""


# ---------------------------------------------------------------------------
class LocalDiskStorage(Storage):
    def __init__(self, root: str = "sessions"):
        self.root = root
        os.makedirs(root, exist_ok=True)

    def _dir(self, session_id: str, *parts: str) -> str:
        return os.path.join(self.root, session_id, *parts)

    def save_feed(self, session_id: str, feed: Feed, which: str = "current") -> None:
        d = self._dir(session_id, which)
        os.makedirs(d, exist_ok=True)
        feed.save(d)

    def load_feed(self, session_id: str, which: str = "current") -> Feed:
        return Feed.load(self._dir(session_id, which))

    def save_state(self, session_id: str, state: dict) -> None:
        os.makedirs(self._dir(session_id), exist_ok=True)
        with open(self._dir(session_id, "state.json"), "w", encoding="utf-8") as fh:
            json.dump(state, fh)

    def load_state(self, session_id: str) -> Optional[dict]:
        path = self._dir(session_id, "state.json")
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def exists(self, session_id: str) -> bool:
        return os.path.isdir(os.path.join(self.root, session_id))

    def delete(self, session_id: str) -> None:
        shutil.rmtree(os.path.join(self.root, session_id), ignore_errors=True)

    def cleanup(self, max_age_seconds: int) -> int:
        now, removed = time.time(), 0
        for sid in os.listdir(self.root):
            if not os.path.isdir(os.path.join(self.root, sid)):
                continue
            state = self.load_state(sid) or {}
            if now - state.get("last_active", 0) > max_age_seconds:
                self.delete(sid)
                removed += 1
        return removed


# ---------------------------------------------------------------------------
class SupabaseStorage(Storage):
    """Feeds as zip objects + state.json in a private Supabase bucket. Uses the
    service-role/secret key — backend only."""

    def __init__(self, url: str, key: str, bucket: str = "gtfs-sessions"):
        from supabase import create_client
        self._client = create_client(url, key)
        self.bucket = bucket
        self._b = self._client.storage.from_(bucket)

    def _path(self, session_id: str, name: str) -> str:
        return f"sessions/{session_id}/{name}"

    def _upload(self, path: str, data: bytes, content_type: str) -> None:
        # upsert so re-saving overwrites; supabase-py wants string option values
        self._b.upload(path, data, {"content-type": content_type, "upsert": "true"})

    def save_feed(self, session_id: str, feed: Feed, which: str = "current") -> None:
        self._upload(self._path(session_id, f"{which}.zip"), feed_to_zip(feed), "application/zip")

    def load_feed(self, session_id: str, which: str = "current") -> Feed:
        return zip_bytes_to_feed(self._b.download(self._path(session_id, f"{which}.zip")))

    def save_state(self, session_id: str, state: dict) -> None:
        self._upload(self._path(session_id, "state.json"),
                     json.dumps(state).encode("utf-8"), "application/json")

    def load_state(self, session_id: str) -> Optional[dict]:
        try:
            return json.loads(self._b.download(self._path(session_id, "state.json")))
        except Exception:
            return None

    def exists(self, session_id: str) -> bool:
        try:
            return len(self._b.list(f"sessions/{session_id}")) > 0
        except Exception:
            return False

    def delete(self, session_id: str) -> None:
        items = self._b.list(f"sessions/{session_id}")
        paths = [self._path(session_id, it["name"]) for it in items]
        if paths:
            self._b.remove(paths)

    def cleanup(self, max_age_seconds: int) -> int:
        now, removed = time.time(), 0
        for it in self._b.list("sessions"):
            sid = it.get("name")
            if not sid:
                continue
            state = self.load_state(sid) or {}
            if now - state.get("last_active", 0) > max_age_seconds:
                self.delete(sid)
                removed += 1
        return removed

    # ----- direct browser->storage upload (bypasses the backend for bytes) --
    def sign_upload(self, path: str) -> dict:
        """A short-lived URL the browser PUTs the file to directly. No key
        reaches the browser — the token in the URL authorizes this one path."""
        res = self._b.create_signed_upload_url(path)
        return {"url": res["signed_url"], "path": res["path"]}

    def download_raw(self, path: str) -> bytes:
        return self._b.download(path)

    def remove_raw(self, path: str) -> None:
        self._b.remove([path])


# ---- feed <-> zip helpers --------------------------------------------------
def feed_to_zip(feed: Feed, only_tables: Optional[List[str]] = None) -> bytes:
    with tempfile.TemporaryDirectory() as d:
        feed.save(d)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for name in sorted(feed.tables):
                if only_tables is not None and name not in only_tables:
                    continue
                zf.write(os.path.join(d, name), arcname=name)
        return buf.getvalue()


def zip_bytes_to_feed(data: bytes) -> Feed:
    with tempfile.TemporaryDirectory() as d:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for member in zf.namelist():
                if member.endswith(".txt") and "/" not in member.strip("/"):
                    zf.extract(member, d)
        return Feed.load(d)


def changed_tables(original: Feed, current: Feed) -> List[str]:
    changed = []
    for name in sorted(set(original.tables) | set(current.tables)):
        o = (original.headers.get(name), original.tables.get(name))
        c = (current.headers.get(name), current.tables.get(name))
        if o != c:
            changed.append(name)
    return changed
