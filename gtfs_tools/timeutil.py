"""GTFS time helpers.

GTFS times are HH:MM:SS strings that MAY exceed 24:00:00 (a trip after
midnight on the same service day, e.g. 25:30:00). We parse to an integer
number of seconds and format back, preserving the >24h convention.
Empty strings (untimed stops) map to/from None.
"""
from __future__ import annotations


def parse_time(value: str | None) -> int | None:
    """'25:30:00' -> 91800 seconds. '' or None -> None."""
    if value is None:
        return None
    value = value.strip()
    if value == "":
        return None
    parts = value.split(":")
    if len(parts) != 3:
        raise ValueError(f"bad GTFS time: {value!r}")
    h, m, s = (int(p) for p in parts)
    return h * 3600 + m * 60 + s


def format_time(seconds: int | None) -> str:
    """91800 -> '25:30:00'. None -> ''."""
    if seconds is None:
        return ""
    if seconds < 0:
        raise ValueError(f"negative GTFS time: {seconds}")
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"
