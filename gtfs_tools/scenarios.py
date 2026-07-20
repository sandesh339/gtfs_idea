"""Scenario registry — the answer keys, written against the REAL sample feed.

Each Scenario bundles the NL request, the human tool-fit hypothesis, and the
oracle (correctness + integrity + damage). This is a representative starter set
across all three groups; expand toward 40. Where a PDF example does not match
the stock feed, the scenario is retargeted and `note` records the divergence.

Helpers keep the answer keys short and declarative.
"""
from __future__ import annotations

from typing import Dict, List

from .feed import Feed
from .grader import Scenario, Check, Checks
from .diffing import cell, EntityChange
from .timeutil import parse_time


# ---- helpers ---------------------------------------------------------------
def service_trips(feed: Feed, service_id: str) -> set:
    return {t["trip_id"] for t in feed.tables.get("trips.txt", [])
            if t.get("service_id") == service_id}


def route_trips(feed: Feed, route_id: str) -> set:
    return {t["trip_id"] for t in feed.tables.get("trips.txt", [])
            if t.get("route_id") == route_id}


def ordered_stops(feed: Feed, trip_id: str) -> List[str]:
    rows = [r for r in feed.tables.get("stop_times.txt", []) if r["trip_id"] == trip_id]
    rows.sort(key=lambda r: int(r["stop_sequence"]))
    return [r["stop_id"] for r in rows]


def stop_time_map(feed: Feed) -> Dict[tuple, tuple]:
    """(trip_id, stop_sequence) -> (arrival, departure)."""
    return {(r["trip_id"], r["stop_sequence"]): (r.get("arrival_time"), r.get("departure_time"))
            for r in feed.tables.get("stop_times.txt", [])}


def last_departure(feed: Feed, trip_id: str) -> int:
    rows = [r for r in feed.tables.get("stop_times.txt", []) if r["trip_id"] == trip_id]
    rows.sort(key=lambda r: int(r["stop_sequence"]))
    return parse_time(rows[-1].get("departure_time")) if rows else None


# ===========================================================================
# Group A — routine parametric edits (tool_fit HIGH)
# ===========================================================================
def _r1_correct(o: Feed, e: Feed) -> List[Check]:
    c = Checks()
    c.eq("stop_name renamed", cell(e, "stops.txt", "stop_id", "STAGECOACH", "stop_name"),
         "Stagecoach Casino")
    return c.items

def _r1_integrity(o: Feed, e: Feed) -> List[Check]:
    c = Checks()
    c.true("stop_id intact", cell(e, "stops.txt", "stop_id", "STAGECOACH", "stop_name") is not None)
    c.eq("stop_lat unchanged", cell(e, "stops.txt", "stop_id", "STAGECOACH", "stop_lat"),
         cell(o, "stops.txt", "stop_id", "STAGECOACH", "stop_lat"))
    refs = sum(1 for r in e.tables["stop_times.txt"] if r["stop_id"] == "STAGECOACH")
    c.true("stop_times references still resolve", refs > 0, f"{refs} refs")
    return c.items

R1 = Scenario(
    id="R1", group="A", tool_fit="high",
    request="Rename the stop 'Stagecoach Hotel & Casino' to 'Stagecoach Casino'.",
    correctness=_r1_correct, integrity=_r1_integrity,
    damage_ok=lambda c, o, e: c.table == "stops.txt" and c.entity_id == "STAGECOACH"
                              and c.kind == "modified",
)


def _r3_correct(o: Feed, e: Feed) -> List[Check]:
    c = Checks()
    c.eq("route_color", cell(e, "routes.txt", "route_id", "CITY", "route_color"), "1E90FF")
    c.eq("route_text_color", cell(e, "routes.txt", "route_id", "CITY", "route_text_color"),
         "FFFFFF")
    return c.items

R3 = Scenario(
    id="R3", group="A", tool_fit="high",
    request="Set the City route colour to 1E90FF and its text colour to FFFFFF.",
    correctness=_r3_correct,
    damage_ok=lambda c, o, e: c.table == "routes.txt" and c.entity_id == "CITY"
                              and c.kind == "modified",
)


def _r5_correct(o: Feed, e: Feed) -> List[Check]:
    c = Checks()
    c.eq("wheelchair_boarding", cell(e, "stops.txt", "stop_id", "BULLFROG",
                                     "wheelchair_boarding"), "1")
    return c.items

R5 = Scenario(
    id="R5", group="A", tool_fit="high",
    request="Mark the 'Bullfrog' stop as wheelchair accessible.",
    correctness=_r5_correct,
    damage_ok=lambda c, o, e: c.table == "stops.txt" and c.entity_id == "BULLFROG"
                              and c.kind == "modified",
)


def _r7_correct(o: Feed, e: Feed) -> List[Check]:
    c = Checks()
    rows = [r for r in e.tables.get("frequencies.txt", [])
            if r["trip_id"] == "CITY1" and r["start_time"] == "10:00:00"]
    c.true("midday CITY1 row exists", len(rows) == 1, f"{len(rows)} rows")
    if rows:
        c.eq("headway_secs", rows[0]["headway_secs"], "1200")
    return c.items

def _r7_integrity(o: Feed, e: Feed) -> List[Check]:
    c = Checks()
    # every OTHER CITY1 frequency row must be unchanged
    o_rows = {r["start_time"]: r["headway_secs"] for r in o.tables["frequencies.txt"]
              if r["trip_id"] == "CITY1"}
    e_rows = {r["start_time"]: r["headway_secs"] for r in e.tables["frequencies.txt"]
              if r["trip_id"] == "CITY1"}
    others_ok = all(e_rows.get(st) == hw for st, hw in o_rows.items() if st != "10:00:00")
    c.true("other CITY1 headways unchanged", others_ok)
    return c.items

R7 = Scenario(
    id="R7", group="A", tool_fit="high",
    request="Change the CITY1 trip's midday window (starting 10:00:00) headway "
            "from 30 to 20 minutes.",
    correctness=_r7_correct, integrity=_r7_integrity,
    damage_ok=lambda c, o, e: c.table == "frequencies.txt" and c.entity_id == "CITY1"
                              and c.kind == "modified",
    note="PDF used AAMV, which has no frequencies row in the stock feed; retargeted "
         "to CITY1 midday (1800->1200).",
)


# ===========================================================================
# Group B — structural cascades (tool_fit LOW)
# ===========================================================================
def _s5_correct(o: Feed, e: Feed) -> List[Check]:
    c = Checks()
    fullw = service_trips(o, "FULLW")
    om, em = stop_time_map(o), stop_time_map(e)
    bad = []
    for (trip, seq), (oa, od) in om.items():
        if trip not in fullw:
            continue
        ea, ed = em.get((trip, seq), (None, None))
        for label, ov, ev in (("arr", oa, ea), ("dep", od, ed)):
            ov_s, ev_s = parse_time(ov), parse_time(ev)
            if ov_s is not None and (ev_s is None or ev_s - ov_s != 900):
                bad.append(f"{trip} seq{seq} {label}: {ov}->{ev}")
    c.true("all FULLW times shifted +900s", not bad, "; ".join(bad[:3]))
    return c.items

S5 = Scenario(
    id="S5", group="B", tool_fit="low",
    request="Push every trip on weekday service FULLW 15 minutes later.",
    correctness=_s5_correct,
    # stop_times shift is required (correctness); shifting the FULLW frequency
    # windows is sanctioned too (delaying trips may move their windows), so it is
    # not counted as damage — but not required, so an FC run that only touches
    # stop_times still passes.
    damage_ok=lambda c, o, e: (c.table in ("stop_times.txt", "frequencies.txt")
                               and c.entity_id in service_trips(o, "FULLW")
                               and c.kind == "modified"),
    note="Frequency-window shift is permitted, not required (labeler-reconciled).",
)


def _find_added_stop(o: Feed, e: Feed, lat: str, lon: str) -> str:
    o_ids = {r["stop_id"] for r in o.tables["stops.txt"]}
    for r in e.tables["stops.txt"]:
        if r["stop_id"] not in o_ids and r.get("stop_lat", "").startswith(lat[:6]):
            return r["stop_id"]
    return None

def _s1_correct(o: Feed, e: Feed) -> List[Check]:
    c = Checks()
    new_id = _find_added_stop(o, e, "36.9088", "-116.7647")
    c.true("new stop added near coords", new_id is not None, str(new_id))
    if new_id:
        for trip in ("CITY1", "CITY2"):
            order = ordered_stops(e, trip)
            if new_id in order and "DADAN" in order and "EMSI" in order:
                i = order.index(new_id)
                neighbours = set(order[max(0, i - 1):i] + order[i + 1:i + 2])
                c.true(f"{trip}: new stop between DADAN and EMSI",
                       {"DADAN", "EMSI"} <= neighbours, f"neighbours={neighbours}")
            else:
                c.true(f"{trip}: new stop present between DADAN/EMSI", False, str(order))
    for trip in ("CITY1", "CITY2"):
        delta = last_departure(e, trip) - last_departure(o, trip)
        c.true(f"{trip}: +3 min downstream", delta == 180, f"delta={delta}s")
    return c.items

def _s1_integrity(o: Feed, e: Feed) -> List[Check]:
    c = Checks()
    for trip in ("CITY1", "CITY2"):
        rows = [r for r in e.tables["stop_times.txt"] if r["trip_id"] == trip]
        seqs = sorted(int(r["stop_sequence"]) for r in rows)
        c.true(f"{trip}: stop_sequence contiguous 1..n", seqs == list(range(1, len(seqs) + 1)),
               str(seqs))
    return c.items

S1 = Scenario(
    id="S1", group="B", tool_fit="low",
    request="Add 'Visitor Center' at (36.9088, -116.7647) on the City route between "
            "'Doing Ave / D Ave N' and 'E Main St / S Irving St', adding 3 min of travel.",
    correctness=_s1_correct, integrity=_s1_integrity,
    damage_ok=lambda c, o, e: ((c.table == "stops.txt" and c.kind == "added")
                               or (c.table == "stop_times.txt"
                                   and c.entity_id in route_trips(o, "CITY")
                                   and c.kind == "modified")),
)


# ===========================================================================
# Group C — under-specified (tool_fit AMBIGUOUS) -> correct = make NO edit
# ===========================================================================
def _ambiguous_correct(o: Feed, e: Feed) -> List[Check]:
    from .diffing import entity_changes
    changes = entity_changes(o, e)
    c = Checks()
    c.true("no edit made (asked instead)", not changes,
           f"{len(changes)} change(s): {[str(x) for x in changes[:3]]}")
    return c.items

A1 = Scenario(
    id="A1", group="C", tool_fit="ambiguous",
    request="Make the morning buses come more often.",
    correctness=_ambiguous_correct,
    damage_ok=lambda c, o, e: False,  # any change is both wrong and damage
    note="Correct behaviour is to clarify before editing. Until the router has a "
         "clarify path, this grades whether the model wrongly edited anyway.",
)


# ---- registry --------------------------------------------------------------
SCENARIOS: Dict[str, Scenario] = {s.id: s for s in (R1, R3, R5, R7, S5, S1, A1)}
