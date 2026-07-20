"""Official MobilityData/Google GTFS validator integration.

Wraps the Java CLI (vendor/gtfs-validator-cli.jar) and exposes a
`Callable[[Feed], List[str]]` that drops into the grader's `validity` slot.

Two design points that make this honest:
1. BASELINE-DELTA. The stock feed already emits ERROR notices (e.g. 13x
   invalid_row_length from short CSV rows). We must not blame the model for
   those. So we validate the ORIGINAL feed round-tripped through our own
   serializer as a baseline, then report only error codes whose count goes UP
   in the edited feed. Round-tripping the baseline cancels pure formatting
   artifacts (our save() always writes full rows), leaving only semantic
   regressions.
2. TIME-FIXED. The sample feed's service is 2007-2010, so we pass -d 2007-07-01
   and -c US so date-based rules don't fire spuriously. Both are configurable.

This is for FINAL grading. The fast in-loop repair signal stays in integrity.py.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from typing import Dict, List, Optional, Tuple

from .feed import Feed

DEFAULT_JAR = os.path.join("vendor", "gtfs-validator-cli.jar")


class OfficialValidator:
    def __init__(self, jar_path: str = DEFAULT_JAR, *, date: Optional[str] = "2007-07-01",
                 country: Optional[str] = "US", skip_update: bool = True,
                 severities: Tuple[str, ...] = ("ERROR",), timeout: int = 180):
        if not os.path.exists(jar_path):
            raise FileNotFoundError(
                f"validator jar not found at {jar_path}; download it into vendor/ "
                f"(see README) or pass jar_path=")
        self.jar_path = jar_path
        self.date = date
        self.country = country
        self.skip_update = skip_update
        self.severities = severities
        self.timeout = timeout
        self._baseline: Optional[Dict[str, int]] = None

    # ----- low level ------------------------------------------------------
    def _error_counts(self, feed: Feed) -> Tuple[Dict[str, int], dict]:
        """Save the feed, run the validator, return {code: count} for the
        tracked severities plus the full parsed report."""
        with tempfile.TemporaryDirectory() as d:
            feed_dir = os.path.join(d, "feed")
            out_dir = os.path.join(d, "out")
            feed.save(feed_dir)
            cmd = ["java", "-jar", self.jar_path, "-i", feed_dir, "-o", out_dir]
            if self.country:
                cmd += ["-c", self.country]
            if self.date:            # omit -d to validate against today's date
                cmd += ["-d", self.date]
            if self.skip_update:
                cmd.append("-svu")
            subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout)
            report_path = os.path.join(out_dir, "report.json")
            if not os.path.exists(report_path):
                raise RuntimeError("validator produced no report.json")
            with open(report_path, encoding="utf-8") as fh:
                report = json.load(fh)
        counts = {n["code"]: n["totalNotices"] for n in report.get("notices", [])
                  if n.get("severity") in self.severities}
        return counts, report

    # ----- public API -----------------------------------------------------
    def set_baseline(self, original: Feed) -> "OfficialValidator":
        """Record the original feed's error profile (round-tripped through our
        serializer) so validate() reports only regressions."""
        self._baseline, _ = self._error_counts(original)
        return self

    def validate(self, feed: Feed) -> List[str]:
        """Return error strings for codes whose count rose above baseline.
        Empty list == the edit introduced no new official ERRORs."""
        counts, _ = self._error_counts(feed)
        base = self._baseline or {}
        errors: List[str] = []
        for code, cnt in sorted(counts.items()):
            delta = cnt - base.get(code, 0)
            if delta > 0:
                errors.append(f"{code} (+{delta}, {cnt} total)")
        return errors

    def report(self, feed: Feed) -> dict:
        """Full parsed report for inspection/debugging."""
        _, rep = self._error_counts(feed)
        return rep


if __name__ == "__main__":
    import sys
    feed = Feed.load(sys.argv[1] if len(sys.argv) > 1 else os.path.join("data", "sample-feed"))
    v = OfficialValidator()
    rep = v.report(feed)
    for n in rep.get("notices", []):
        print(f"{n['severity']:<8} {n['code']:<42} x{n['totalNotices']}")
