"""User-facing feed validation for the app.

One report shape, three backends, chosen by env:
  VALIDATOR_URL set          -> RemoteOfficialValidator (Cloud Run, official jar)
  else local Java + jar       -> LocalOfficialValidator (official jar on this box)
  else                        -> LightweightValidator (integrity.py fallback)

Report shape (JSON):
  { "source": str, "error_count": int, "warning_count": int,
    "notices": [ {"severity","code","count","samples":[...]} ] }

This validates the FULL current feed (not baseline-delta) — the natural
"is my feed valid?" report a reviewer wants.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod

from gtfs_tools import Feed


def _from_report_json(report: dict, source: str) -> dict:
    """Shape an official gtfs-validator report.json into our report shape."""
    notices, errors, warnings = [], 0, 0
    for n in report.get("notices", []):
        sev = n.get("severity", "INFO")
        total = n.get("totalNotices", 0)
        if sev == "ERROR":
            errors += total
        elif sev == "WARNING":
            warnings += total
        notices.append({"severity": sev, "code": n.get("code", ""),
                        "count": total, "samples": (n.get("sampleNotices") or [])[:3]})
    # errors first, then warnings, then info; most frequent first within a group
    order = {"ERROR": 0, "WARNING": 1, "INFO": 2}
    notices.sort(key=lambda x: (order.get(x["severity"], 3), -x["count"]))
    return {"source": source, "error_count": errors, "warning_count": warnings, "notices": notices}


class Validator(ABC):
    @abstractmethod
    def validate(self, feed: Feed) -> dict: ...


class LocalOfficialValidator(Validator):
    """The official MobilityData validator via the local Java jar."""

    def __init__(self, jar_path: str):
        from gtfs_tools.gtfs_validator import OfficialValidator
        # date=None -> validate against today; country=None -> skip locale rules
        self._v = OfficialValidator(jar_path, date=None, country=None)

    def validate(self, feed: Feed) -> dict:
        return _from_report_json(self._v.report(feed), "Official GTFS Validator (local)")


class RemoteOfficialValidator(Validator):
    """The official validator running as a remote service (e.g. Cloud Run).
    POSTs the feed zip and expects the validator's report.json back."""

    def __init__(self, url: str, token: str = ""):
        self.url = url.rstrip("/")
        self.token = token

    def validate(self, feed: Feed) -> dict:
        import requests
        from .storage import feed_to_zip
        headers = {"X-Validator-Token": self.token} if self.token else {}
        resp = requests.post(f"{self.url}/validate",
                             files={"file": ("feed.zip", feed_to_zip(feed), "application/zip")},
                             headers=headers, timeout=120)
        resp.raise_for_status()
        return _from_report_json(resp.json(), "Official GTFS Validator (cloud)")


class LightweightValidator(Validator):
    """Fallback: the fast structural checks from integrity.py."""

    def validate(self, feed: Feed) -> dict:
        from gtfs_tools.integrity import validate_feed
        errs = validate_feed(feed)
        notices = [{"severity": "ERROR", "code": "structural", "count": 1, "samples": [{"message": e}]}
                   for e in errs]
        return {"source": "lightweight structural checks",
                "error_count": len(errs), "warning_count": 0, "notices": notices}


def make_validator() -> Validator:
    url = os.getenv("VALIDATOR_URL")
    if url:
        return RemoteOfficialValidator(url, os.getenv("VALIDATOR_TOKEN", ""))
    jar = os.getenv("GTFS_VALIDATOR_JAR", os.path.join("vendor", "gtfs-validator-cli.jar"))
    if os.path.exists(jar):
        try:
            return LocalOfficialValidator(jar)
        except Exception:
            pass
    return LightweightValidator()
