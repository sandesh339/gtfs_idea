"""Lightweight structural validator used to drive the repair loop.

This is NOT the official GTFS validator and NOT the per-scenario oracle — it
is a cheap, scenario-agnostic referential/ordering check so the FC path has a
real failure signal to repair against (matched to code-gen's repair channel).
The full GTFS validator + answer-key grading come later.
"""
from __future__ import annotations

from typing import List

from .feed import Feed
from .timeutil import parse_time


def validate_feed(feed: Feed) -> List[str]:
    errors: List[str] = []
    stops = {r["stop_id"] for r in feed.tables.get("stops.txt", [])}
    trips = {r["trip_id"] for r in feed.tables.get("trips.txt", [])}
    routes = {r["route_id"] for r in feed.tables.get("routes.txt", [])}

    # referential integrity
    for t in feed.tables.get("trips.txt", []):
        if t.get("route_id") not in routes:
            errors.append(f"trip {t['trip_id']} references missing route {t.get('route_id')!r}")

    # per-trip stop_times: ordering, references, monotonic times
    by_trip: dict[str, list] = {}
    for r in feed.tables.get("stop_times.txt", []):
        if r["stop_id"] not in stops:
            errors.append(f"stop_time on {r['trip_id']} references missing stop {r['stop_id']!r}")
        if r["trip_id"] not in trips:
            errors.append(f"stop_time references missing trip {r['trip_id']!r}")
        by_trip.setdefault(r["trip_id"], []).append(r)

    for trip_id, rows in by_trip.items():
        seqs = sorted(int(r["stop_sequence"]) for r in rows)
        if len(set(seqs)) != len(seqs):
            errors.append(f"trip {trip_id} has duplicate stop_sequence values")
        ordered = sorted(rows, key=lambda r: int(r["stop_sequence"]))
        prev = None
        for r in ordered:
            for col in ("arrival_time", "departure_time"):
                secs = parse_time(r.get(col))
                if secs is None:
                    continue
                if prev is not None and secs < prev:
                    errors.append(
                        f"trip {trip_id} times not monotonic at seq {r['stop_sequence']} ({col})")
                prev = secs
    return errors
