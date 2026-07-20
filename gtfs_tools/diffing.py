"""Entity-level diff between two feeds — the basis of the `damage` dimension.

Each table has a primary ENTITY key. Two feeds are compared entity by entity:
an entity "changed" if its multiset of rows differs. This granularity is what
makes damage detection robust to the things that AREN'T damage:
  - adding an empty column globally (ensure_column) -> compared as "" == ""
  - reordering columns -> rows compared as unordered (col,val) sets
  - renumbering stop_sequence within a trip -> the whole trip is one entity,
    so a legitimate rewrite shows up as ONE changed entity, not N cell edits.

stop_times group by trip_id (a trip's rows are one unit); frequencies likewise.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Optional

from .feed import Feed

ENTITY_KEY: Dict[str, str] = {
    "agency.txt": "agency_id",
    "stops.txt": "stop_id",
    "routes.txt": "route_id",
    "trips.txt": "trip_id",
    "stop_times.txt": "trip_id",   # a trip's stop_times are one unit
    "frequencies.txt": "trip_id",
    "calendar.txt": "service_id",
    "calendar_dates.txt": "service_id",
    "shapes.txt": "shape_id",
}


@dataclass(frozen=True)
class EntityChange:
    table: str
    entity_id: str
    kind: str  # "modified" | "added" | "removed"

    def __str__(self) -> str:
        return f"{self.kind} {self.table}:{self.entity_id}"


def _row_key(row: dict, cols: List[str]) -> tuple:
    # normalise None (a present-but-empty cell) to "" so it never reads as a change
    return tuple((c, "" if row.get(c) is None else row.get(c)) for c in cols)


def _group(feed: Feed, table: str, key: str, cols: List[str]) -> Dict[str, Counter]:
    groups: Dict[str, Counter] = {}
    for row in feed.tables.get(table, []):
        eid = row.get(key, "")
        groups.setdefault(eid, Counter())[_row_key(row, cols)] += 1
    return groups


def entity_changes(original: Feed, edited: Feed) -> List[EntityChange]:
    changes: List[EntityChange] = []
    tables = set(original.tables) | set(edited.tables)
    for table in sorted(tables):
        key = ENTITY_KEY.get(table)
        if key is None:
            continue
        cols = sorted(set(original.headers.get(table, [])) |
                      set(edited.headers.get(table, [])))
        o = _group(original, table, key, cols)
        e = _group(edited, table, key, cols)
        for eid in sorted(set(o) | set(e)):
            if o.get(eid) == e.get(eid):
                continue
            kind = ("added" if eid not in o else
                    "removed" if eid not in e else "modified")
            changes.append(EntityChange(table, eid, kind))
    return changes


def cell(feed: Feed, table: str, key_col: str, key_val: str, col: str) -> Optional[str]:
    """Convenience for correctness assertions: one cell, or None if absent."""
    for row in feed.tables.get(table, []):
        if row.get(key_col) == key_val:
            return row.get(col)
    return None


# tables with exactly one row per entity -> show field-level changes
_SINGLE_ROW = {"agency.txt", "stops.txt", "routes.txt", "trips.txt", "calendar.txt"}
_NOUN = {"agency.txt": "agency", "stops.txt": "stop", "routes.txt": "route",
         "trips.txt": "trip", "stop_times.txt": "trip", "frequencies.txt": "trip",
         "calendar.txt": "service"}
_NAME_COL = {"stops.txt": "stop_name", "routes.txt": "route_long_name",
             "agency.txt": "agency_name"}


def _rows_for(feed: Feed, table: str, entity_id: str) -> List[dict]:
    key = ENTITY_KEY[table]
    return [r for r in feed.tables.get(table, []) if r.get(key) == entity_id]


def _geo(row: dict):
    try:
        return [float(row["stop_lon"]), float(row["stop_lat"])]
    except (KeyError, ValueError, TypeError):
        return None


def _field_diffs(b: dict, a: dict) -> List[dict]:
    cols = sorted(set(b) | set(a))
    return [{"col": c, "before": b.get(c, ""), "after": a.get(c, "")}
            for c in cols if (b.get(c) or "") != (a.get(c) or "")]


def _seq(feed: Feed, trip_id: str) -> List[dict]:
    rows = [r for r in feed.tables.get("stop_times.txt", []) if r["trip_id"] == trip_id]
    rows.sort(key=lambda r: int(r["stop_sequence"]))
    return [{"seq": r["stop_sequence"], "stop_id": r["stop_id"],
             "arr": r.get("arrival_time", ""), "dep": r.get("departure_time", "")} for r in rows]


def _freq(feed: Feed, trip_id: str) -> List[dict]:
    return [{"start": r.get("start_time", ""), "end": r.get("end_time", ""),
             "headway": r.get("headway_secs", "")}
            for r in feed.tables.get("frequencies.txt", []) if r["trip_id"] == trip_id]


def structured_diff(before: Feed, after: Feed, cap: int = 12) -> dict:
    """Rich per-change records (with before/after values + geo) for the inline
    changes view. Detailed records are capped; the rest are summarized in totals."""
    changes = entity_changes(before, after)
    totals: dict = {}
    for ch in changes:
        totals.setdefault(ch.table, {}).setdefault(ch.kind, 0)
        totals[ch.table][ch.kind] += 1

    records = []
    for ch in changes[:cap]:
        rec = {"table": ch.table, "entity": ch.entity_id, "kind": ch.kind}
        if ch.table == "stops.txt":
            b = (_rows_for(before, ch.table, ch.entity_id) or [{}])[0]
            a = (_rows_for(after, ch.table, ch.entity_id) or [{}])[0]
            rec["fields"] = _field_diffs(b, a)
            rec["geo"] = {"before": _geo(b), "after": _geo(a),
                          "name": a.get("stop_name") or b.get("stop_name") or ch.entity_id}
        elif ch.table in ("routes.txt", "agency.txt", "trips.txt", "calendar.txt"):
            b = (_rows_for(before, ch.table, ch.entity_id) or [{}])[0]
            a = (_rows_for(after, ch.table, ch.entity_id) or [{}])[0]
            rec["fields"] = _field_diffs(b, a)
        elif ch.table == "stop_times.txt":
            rec["seq_before"] = _seq(before, ch.entity_id)
            rec["seq_after"] = _seq(after, ch.entity_id)
        elif ch.table == "frequencies.txt":
            rec["rows_before"] = _freq(before, ch.entity_id)
            rec["rows_after"] = _freq(after, ch.entity_id)
        records.append(rec)

    return {"records": records, "extra": max(0, len(changes) - cap), "totals": totals}


def summarize_changes(before: Feed, after: Feed, max_lines: int = 25) -> List[str]:
    """Human-readable summary of what changed between two feeds, for the chat UI."""
    lines: List[str] = []
    for ch in entity_changes(before, after):
        noun = _NOUN.get(ch.table, ch.table)
        if ch.kind == "added":
            rows = _rows_for(after, ch.table, ch.entity_id)
            name = rows[0].get(_NAME_COL.get(ch.table, ""), "") if rows else ""
            extra = f" ('{name}')" if name else ""
            lines.append(f"+ added {noun} {ch.entity_id}{extra}"
                         + (f" with {len(rows)} rows" if ch.table == "stop_times.txt" else ""))
        elif ch.kind == "removed":
            lines.append(f"- removed {noun} {ch.entity_id}")
        elif ch.table in _SINGLE_ROW:
            b = (_rows_for(before, ch.table, ch.entity_id) or [{}])[0]
            a = (_rows_for(after, ch.table, ch.entity_id) or [{}])[0]
            cols = sorted(set(b) | set(a))
            fields = [f"{c} {b.get(c, '')!r} -> {a.get(c, '')!r}"
                      for c in cols if (b.get(c) or "") != (a.get(c) or "")]
            lines.append(f"~ {noun} {ch.entity_id}: " + ", ".join(fields))
        else:  # stop_times / frequencies grouped by trip
            nb, na = len(_rows_for(before, ch.table, ch.entity_id)), \
                     len(_rows_for(after, ch.table, ch.entity_id))
            tbl = ch.table.replace(".txt", "")
            change = f"{nb}→{na} rows" if nb != na else f"{na} rows updated"
            lines.append(f"~ {noun} {ch.entity_id}: {tbl} {change}")
        if len(lines) >= max_lines:
            lines.append("  ... (more changes)")
            break
    return lines
