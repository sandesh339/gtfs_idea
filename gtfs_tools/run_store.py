"""Persist a run's edited feed compactly, so correctness/damage grading can be
re-run OFFLINE (no API) later.

We store only the tables that DIFFER from the pristine feed (full content of each
changed table + its headers), gzipped. Reconstruction is exact: clone pristine,
overwrite the changed tables, drop any removed ones. This avoids row-identity
headaches (stop_sequence can change) at the cost of storing whole changed tables
-- attribute edits touch tiny tables; structural edits store the changed
stop_times/trips. Everything is deterministic, so a saved run can be graded by
any present or future oracle without touching the model again.
"""
from __future__ import annotations

import gzip
import json
import os
from typing import Dict, List, Tuple

from .feed import Feed


def diff_tables(pristine: Feed, edit: Feed) -> Tuple[Dict[str, List[dict]], List[str], Dict[str, List[str]]]:
    """Tables whose rows/headers differ or are new; names removed; changed headers."""
    changed, headers = {}, {}
    for name, rows in edit.tables.items():
        if (name not in pristine.tables
                or pristine.tables[name] != rows
                or pristine.headers.get(name) != edit.headers.get(name)):
            changed[name] = rows
            headers[name] = edit.headers.get(name, list(rows[0].keys()) if rows else [])
    removed = [n for n in pristine.tables if n not in edit.tables]
    return changed, removed, headers


def save_edit(path: str, pristine: Feed, edit: Feed) -> str:
    """Write the pristine->edit delta to `path` (gzipped JSON). Returns the path."""
    changed, removed, headers = diff_tables(pristine, edit)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump({"changed": changed, "headers": headers, "removed": removed}, fh)
    return path


def load_edit(path: str, pristine: Feed) -> Feed:
    """Reconstruct the edited feed = pristine + saved delta. Exact, offline."""
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        payload = json.load(fh)
    feed = pristine.copy()
    for name, rows in payload["changed"].items():
        feed.tables[name] = rows
        feed.headers[name] = payload["headers"].get(name, list(rows[0].keys()) if rows else [])
    for name in payload.get("removed", []):
        feed.tables.pop(name, None)
        feed.headers.pop(name, None)
    return feed
