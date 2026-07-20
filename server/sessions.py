"""Session store with reconstruct-from-storage (survives Render spin-down).

Sessions live in memory for speed, but the source of truth is Storage: the
current feed and state.json (history + timestamps) are written after every edit.
On a cache miss (cold start / new instance), get() REBUILDS the ChatSession from
storage instead of 404-ing. Undo is in-memory only (not persisted).
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, Optional

from gtfs_tools import Feed
from gtfs_tools.chat import ChatSession
from gtfs_tools.llm import LLMClient

from .storage import Storage


@dataclass
class SessionRecord:
    session_id: str
    chat: ChatSession
    created: float
    last_active: float = field(default_factory=time.time)


class SessionStore:
    def __init__(self, client: LLMClient, storage: Storage, ttl_seconds: int = 48 * 3600):
        self.client = client
        self.storage = storage
        self.ttl = ttl_seconds
        self._sessions: Dict[str, SessionRecord] = {}
        self._lock = threading.Lock()

    # ----- lifecycle ------------------------------------------------------
    def create(self, feed: Feed) -> str:
        sid = uuid.uuid4().hex
        chat = ChatSession(feed, self.client)
        rec = SessionRecord(sid, chat, time.time())
        with self._lock:
            self._sessions[sid] = rec
        self.storage.save_feed(sid, feed, "original")
        self.storage.save_feed(sid, feed, "current")
        self.storage.save_state(sid, self._state_of(rec))
        return sid

    def get(self, session_id: str) -> Optional[ChatSession]:
        self._sweep()
        with self._lock:
            rec = self._sessions.get(session_id)
            if rec is not None:
                rec.last_active = time.time()
                return rec.chat
        return self._reconstruct(session_id)

    def persist(self, session_id: str) -> None:
        with self._lock:
            rec = self._sessions.get(session_id)
        if rec is None:
            return
        rec.last_active = time.time()
        self.storage.save_feed(session_id, rec.chat.feed, "current")
        self.storage.save_state(session_id, self._state_of(rec))

    def cleanup(self, max_age_seconds: int) -> int:
        return self.storage.cleanup(max_age_seconds)

    # ----- internals ------------------------------------------------------
    def _reconstruct(self, session_id: str) -> Optional[ChatSession]:
        with self._lock:
            rec = self._sessions.get(session_id)   # another thread may have won
            if rec is not None:
                return rec.chat
        if not self.storage.exists(session_id):
            return None
        try:
            current = self.storage.load_feed(session_id, "current")
            original = self.storage.load_feed(session_id, "original")
        except Exception:
            return None
        state = self.storage.load_state(session_id) or {}
        chat = ChatSession.from_state(current, original, state.get("history", []), self.client)
        rec = SessionRecord(session_id, chat, state.get("created", time.time()))
        with self._lock:
            self._sessions[session_id] = rec
        return chat

    def _state_of(self, rec: SessionRecord) -> dict:
        return {"history": rec.chat.history, "created": rec.created,
                "last_active": time.time()}

    def _sweep(self) -> None:
        now = time.time()
        with self._lock:
            dead = [s for s, r in self._sessions.items() if now - r.last_active > self.ttl]
            for s in dead:
                del self._sessions[s]
