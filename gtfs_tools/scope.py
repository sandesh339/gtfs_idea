"""Scope selector grammar — the one honesty anchor of the FC library.

The two set-level tools (shift_times, renumber_sequence) are the only places
where a single call can touch many rows. To keep set-power from leaking in
per-tool, BOTH consume the same tiny selector grammar:

    selector := <field><op><value> [ AND <field><op><value> ]*
    field    := route | service | trip | direction | seq
    op       := =  >  <  >=  <=        (only '=' for route/service/trip/direction)
    examples : route=CITY
               service=FULLW
               trip=CITY1 AND seq>4

A selector resolves to a set of stop_times rows: the trip-level fields
(route/service/trip/direction) filter trips via trips.txt, and `seq` filters
stop_sequence on the resulting stop_times rows.
"""
from __future__ import annotations

from typing import List, Tuple

from .feed import Feed

# field name in the selector -> column name in trips.txt
_TRIP_FIELDS = {
    "route": "route_id",
    "service": "service_id",
    "trip": "trip_id",
    "direction": "direction_id",
}
_OPS = {"=", ">", "<", ">=", "<="}

Cond = Tuple[str, str, str]  # (field, op, value)


def parse_selector(selector: str) -> List[Cond]:
    conds: List[Cond] = []
    for clause in selector.split(" AND "):
        clause = clause.strip()
        if not clause:
            continue
        op = next((o for o in (">=", "<=", "=", ">", "<") if o in clause), None)
        if op is None:
            raise ValueError(f"no operator in clause: {clause!r}")
        field, value = clause.split(op, 1)
        field, value = field.strip(), value.strip()
        if field not in _TRIP_FIELDS and field != "seq":
            raise ValueError(f"unknown scope field: {field!r}")
        if field != "seq" and op != "=":
            raise ValueError(f"field {field!r} only supports '='")
        conds.append((field, op, value))
    if not conds:
        raise ValueError("empty selector")
    return conds


def _cmp_seq(row_value: str, op: str, target: str) -> bool:
    a, b = int(row_value), int(target)
    return {
        "=": a == b, ">": a > b, "<": a < b, ">=": a >= b, "<=": a <= b,
    }[op]


def resolve_stop_time_indices(feed: Feed, selector: str) -> List[int]:
    """Indices into stop_times.txt that the selector matches."""
    conds = parse_selector(selector)
    trip_conds = [(c[0], c[2]) for c in conds if c[0] in _TRIP_FIELDS]
    seq_conds = [(c[1], c[2]) for c in conds if c[0] == "seq"]

    trips = feed.tables.get("trips.txt", [])
    if trip_conds:
        allowed = {
            t["trip_id"]
            for t in trips
            if all(t.get(_TRIP_FIELDS[f], "") == v for f, v in trip_conds)
        }
    else:
        allowed = {t["trip_id"] for t in trips}

    idxs: List[int] = []
    for i, row in enumerate(feed.tables.get("stop_times.txt", [])):
        if row["trip_id"] not in allowed:
            continue
        if all(_cmp_seq(row["stop_sequence"], op, v) for op, v in seq_conds):
            idxs.append(i)
    return idxs


def resolve_trip_ids(feed: Feed, selector: str) -> List[str]:
    """Trip ids that have at least one stop_times row in scope (order-stable)."""
    seen, out = set(), []
    rows = feed.tables.get("stop_times.txt", [])
    for i in resolve_stop_time_indices(feed, selector):
        tid = rows[i]["trip_id"]
        if tid not in seen:
            seen.add(tid)
            out.append(tid)
    return out
