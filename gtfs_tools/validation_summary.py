"""Canonical validator report summary for the benchmark.

Runs the official MobilityData jar locally, baseline-delta (edited vs original),
and returns a compact per-result summary attached to every benchmark row.
Baselines are cached per feed; identical edited feeds are cached by content hash
so the same output isn't re-validated across trials/models.
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Dict, Optional

from .feed import Feed
from .gtfs_validator import OfficialValidator, DEFAULT_JAR


def representative_date(feed: Feed) -> Optional[str]:
    """A YYYYMMDD date INSIDE the feed's service window, for reproducible
    date-sensitive validation. Without this the validator uses 'today', so the
    'valid' dimension drifts day-to-day and date-window notices (expired_calendar,
    service-never-active) leak into the baseline. Uses the intersection of all
    calendar spans when non-empty, else the midpoint of their union; falls back
    to the median calendar_dates date; None if the feed has no dated service.
    Returned as YYYY-MM-DD (the format the validator CLI's -d flag expects)."""
    def fmt(yyyymmdd: str) -> Optional[str]:
        try:
            return datetime.strptime(yyyymmdd, "%Y%m%d").strftime("%Y-%m-%d")
        except ValueError:
            return None

    cal = feed.tables.get("calendar.txt", [])
    starts = [c["start_date"] for c in cal if c.get("start_date")]
    ends = [c["end_date"] for c in cal if c.get("end_date")]
    if starts and ends:
        lo, hi = max(starts), min(ends)          # intersection of every span
        if lo > hi:                              # spans disjoint -> use union
            lo, hi = min(starts), max(ends)
        try:
            d0 = datetime.strptime(lo, "%Y%m%d")
            d1 = datetime.strptime(hi, "%Y%m%d")
            return (d0 + (d1 - d0) / 2).strftime("%Y-%m-%d")
        except ValueError:
            pass
    dates = sorted(c["date"] for c in feed.tables.get("calendar_dates.txt", []) if c.get("date"))
    return fmt(dates[len(dates) // 2]) if dates else None


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
    def __init__(self, jar_path: str = DEFAULT_JAR, date: Optional[str] = None):
        self._jar = jar_path
        self._default_date = date                          # used if a feed has no pinned date
        self._validators: Dict[Optional[str], OfficialValidator] = {}  # date -> validator
        self._feed_date: Dict[str, Optional[str]] = {}     # feed_key -> pinned YYYYMMDD
        self._baseline: Dict[str, Dict[str, tuple]] = {}   # feed_key -> {code: (sev, count)}
        self._edited: Dict[str, dict] = {}                 # hash -> summary

    def set_feed_date(self, feed_key: str, date: Optional[str]) -> None:
        """Pin the validation date for a feed (call before baseline())."""
        self._feed_date[feed_key] = date

    def _validator(self, date: Optional[str]) -> OfficialValidator:
        if date not in self._validators:
            self._validators[date] = OfficialValidator(self._jar, date=date, country=None)
        return self._validators[date]

    def _counts(self, feed: Feed, date: Optional[str]) -> Dict[str, tuple]:
        rep = self._validator(date).report(feed)
        return {n["code"]: (n.get("severity", "INFO"), n.get("totalNotices", 0))
                for n in rep.get("notices", [])}

    def baseline(self, original: Feed, feed_key: str) -> Dict[str, tuple]:
        if feed_key not in self._baseline:
            date = self._feed_date.get(feed_key, self._default_date)
            self._baseline[feed_key] = self._counts(original, date)
        return self._baseline[feed_key]

    def summarize(self, original: Feed, edited: Feed, feed_key: str) -> dict:
        base = self.baseline(original, feed_key)
        date = self._feed_date.get(feed_key, self._default_date)
        key = feed_key + ":" + feed_hash(edited)
        if key in self._edited:
            return self._edited[key]
        edited_counts = self._counts(edited, date)
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
