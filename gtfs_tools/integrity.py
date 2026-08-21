"""Lightweight structural validator used to drive the repair loop.

This is NOT the official GTFS validator and NOT the per-scenario oracle — it
is a cheap, scenario-agnostic referential/ordering check so the FC path has a
real failure signal to repair against (matched to code-gen's repair channel).
The full GTFS validator + answer-key grading come later.
"""
from __future__ import annotations

from typing import List

from .feed import Feed, seq_int
from .timeutil import parse_time


# GTFS integer-typed fields a generated program commonly floatifies (e.g. pandas
# turns a column to float64 once it holds a NaN, so stop_sequence serialises as
# "1.0"). The official validator rejects that as invalid_integer, but seq_int()
# tolerates it, so the repair loop never saw it. Flag it here (deduped per field).
_INT_FIELDS = {
    "stop_times.txt": ("stop_sequence",),
    "trips.txt": ("direction_id",),
    "calendar.txt": ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"),
    "calendar_dates.txt": ("exception_type",),
}


def _bad_int(v) -> bool:
    v = (v or "").strip()
    return v != "" and not v.isdigit()   # "1.0", "-1", "1e0" -> True; "1"/"" -> False


def validate_feed(feed: Feed) -> List[str]:
    errors: List[str] = []
    stops = {r["stop_id"] for r in feed.tables.get("stops.txt", [])}
    trips = {r["trip_id"] for r in feed.tables.get("trips.txt", [])}
    routes = {r["route_id"] for r in feed.tables.get("routes.txt", [])}

    # integer-format check (one representative error per field, not per row)
    for table, cols in _INT_FIELDS.items():
        for col in cols:
            bad = next((r.get(col) for r in feed.tables.get(table, []) if _bad_int(r.get(col))), None)
            if bad is not None:
                errors.append(f"{table}: {col}={bad!r} is not a valid integer — write integers "
                              f"like '1', not '1.0' (cast to int before serialising)")

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
        seqs = sorted(seq_int(r["stop_sequence"]) for r in rows)
        if len(set(seqs)) != len(seqs):
            errors.append(f"trip {trip_id} has duplicate stop_sequence values")
        ordered = sorted(rows, key=lambda r: seq_int(r["stop_sequence"]))
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

    # block conflicts: trips sharing a block_id (on the same service) are one
    # vehicle's consecutive work, so their stop_times must NOT overlap in time.
    # Structural edits that shift/add/mirror trips commonly introduce these; the
    # repair loop resolves them by clearing block_id on the affected trips
    # (block_id is optional). One representative error is enough to drive repair.
    meta = {t["trip_id"]: (t.get("block_id", "").strip(), t.get("service_id", ""))
            for t in feed.tables.get("trips.txt", [])}
    blocks: dict = {}
    for trip_id, rows in by_trip.items():
        blk, svc = meta.get(trip_id, ("", ""))
        if not blk:
            continue
        secs = [s for r in rows
                for s in (parse_time(r.get("departure_time")), parse_time(r.get("arrival_time")))
                if s is not None]
        if secs:
            blocks.setdefault((blk, svc), []).append((min(secs), max(secs), trip_id))
    for (blk, _svc), spans in blocks.items():
        spans.sort()
        hit = next((i for i in range(1, len(spans)) if spans[i][0] < spans[i - 1][1]), None)
        if hit is not None:
            a, b = spans[hit - 1], spans[hit]
            errors.append(f"trips {a[2]} and {b[2]} share block_id {blk!r} but their stop_times "
                          f"overlap in time (one vehicle can't be in two places) — clear block_id "
                          f"on the affected trips (it is optional) or reschedule them")
            break
    return errors
