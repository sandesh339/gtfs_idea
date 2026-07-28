"""Canonical validator report summary for the benchmark.

Runs the official MobilityData jar locally, baseline-delta (edited vs original),
and returns a compact per-result summary attached to every benchmark row.
Baselines are cached per feed; identical edited feeds are cached by content hash
so the same output isn't re-validated across trials/models.
"""
from __future__ import annotations

import hashlib
from typing import Dict, Optional

from .feed import Feed
from .gtfs_validator import OfficialValidator, DEFAULT_JAR


def feed_hash(feed: Feed) -> str:
    h = hashlib.md5()
    for name in sorted(feed.tables):
        cols = feed.headers.get(name, [])
        h.update(name.encode())
        h.update("\x1f".join(cols).encode())
        for row in feed.tables[name]:
            h.update("\x1f".join((row.get(c) or "") for c in cols).encode())
        h.update(b"\x1e")
    return h.hexdigest()


class ValidatorSummarizer:
    def __init__(self, jar_path: str = DEFAULT_JAR):
        # date=None -> validate against today; report() returns all severities
        self._v = OfficialValidator(jar_path, date=None, country=None)
        self._baseline: Dict[str, Dict[str, tuple]] = {}   # feed_key -> {code: (sev, count)}
        self._edited: Dict[str, dict] = {}                 # hash -> summary

    def _counts(self, feed: Feed) -> Dict[str, tuple]:
        rep = self._v.report(feed)
        return {n["code"]: (n.get("severity", "INFO"), n.get("totalNotices", 0))
                for n in rep.get("notices", [])}

    def baseline(self, original: Feed, feed_key: str) -> Dict[str, tuple]:
        if feed_key not in self._baseline:
            self._baseline[feed_key] = self._counts(original)
        return self._baseline[feed_key]

    def summarize(self, original: Feed, edited: Feed, feed_key: str) -> dict:
        base = self.baseline(original, feed_key)
        key = feed_key + ":" + feed_hash(edited)
        if key in self._edited:
            return self._edited[key]
        edited_counts = self._counts(edited)
        errors, warnings, codes = 0, 0, {}
        for code, (sev, cnt) in edited_counts.items():
            delta = cnt - base.get(code, (sev, 0))[1]
            if delta <= 0:
                continue
            if sev == "ERROR":
                errors += delta
                codes[code] = delta
            elif sev == "WARNING":
                warnings += delta
        summary = {"source": "official-v8 (local)", "introduced_errors": errors,
                   "introduced_codes": codes, "introduced_warnings": warnings,
                   "valid": errors == 0}
        self._edited[key] = summary
        return summary
