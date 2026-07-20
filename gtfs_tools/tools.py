"""The frozen function-calling library.

These are the *very required* primitives for editing a GTFS feed, designed
around edit TYPES, not scenarios. Litmus test passed by every tool here:
"would this exist if I had never seen the scenarios?"

Four buckets:
  READ          - expose the feed so the model can gather ids/counts before editing
  WRITE-SINGLE  - mutate exactly one row, fully explicit, no hidden cascades
  WRITE-SCOPE   - the only set-level ops; both share the scope grammar (scope.py)
  LIFECYCLE     - finish() signals the edit is done -> triggers validation

Each method returns a structured observation: {"ok": True, ...} or
{"ok": False, "error": "..."}. That observation is fed back into the ReAct
loop and is what lets the model chain calls.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from .feed import Feed, Row
from . import scope as scope_mod
from .timeutil import parse_time, format_time


class GTFSToolkit:
    def __init__(self, feed: Feed) -> None:
        self.feed = feed
        self.finished = False

    # ===== helpers (not exposed as tools) ================================
    def _stop_time_row(self, trip_id: str, stop_sequence: str) -> Optional[Row]:
        for r in self.feed.tables.get("stop_times.txt", []):
            if r["trip_id"] == trip_id and r["stop_sequence"] == str(stop_sequence):
                return r
        return None

    def _find_one(self, table: str, key: str, value: str) -> Optional[Row]:
        for r in self.feed.tables.get(table, []):
            if r.get(key) == value:
                return r
        return None

    # ===== READ ==========================================================
    def find_stop(self, query: str) -> Dict:
        """Look up stops by stop_id (exact) or stop_name (case-insensitive substring)."""
        q = query.lower()
        hits = [
            {"stop_id": r["stop_id"], "stop_name": r.get("stop_name", ""),
             "stop_lat": r.get("stop_lat", ""), "stop_lon": r.get("stop_lon", "")}
            for r in self.feed.tables.get("stops.txt", [])
            if r["stop_id"] == query or q in r.get("stop_name", "").lower()
        ]
        return {"ok": True, "matches": hits, "count": len(hits)}

    def find_route(self, query: str) -> Dict:
        """Look up routes by route_id (exact) or short/long name (substring)."""
        q = query.lower()
        hits = [
            {"route_id": r["route_id"], "route_short_name": r.get("route_short_name", ""),
             "route_long_name": r.get("route_long_name", "")}
            for r in self.feed.tables.get("routes.txt", [])
            if r["route_id"] == query
            or q in r.get("route_short_name", "").lower()
            or q in r.get("route_long_name", "").lower()
        ]
        return {"ok": True, "matches": hits, "count": len(hits)}

    def find_trip(self, query: str, route_id: Optional[str] = None) -> Dict:
        """Look up trips by trip_id (exact) or headsign (substring), optionally on a route."""
        q = query.lower()
        hits = [
            {"trip_id": r["trip_id"], "route_id": r.get("route_id", ""),
             "service_id": r.get("service_id", ""), "direction_id": r.get("direction_id", ""),
             "trip_headsign": r.get("trip_headsign", "")}
            for r in self.feed.tables.get("trips.txt", [])
            if (r["trip_id"] == query or q in r.get("trip_headsign", "").lower())
            and (route_id is None or r.get("route_id") == route_id)
        ]
        return {"ok": True, "matches": hits, "count": len(hits)}

    def find_agency(self, query: str) -> Dict:
        """Look up agencies by agency_id (exact) or agency_name (substring)."""
        q = query.lower()
        hits = [
            {"agency_id": r.get("agency_id", ""), "agency_name": r.get("agency_name", "")}
            for r in self.feed.tables.get("agency.txt", [])
            if r.get("agency_id") == query or q in r.get("agency_name", "").lower()
        ]
        return {"ok": True, "matches": hits, "count": len(hits)}

    def list_trips(self, route_id: str, service_id: Optional[str] = None,
                   direction_id: Optional[str] = None) -> Dict:
        """List trip_ids on a route, optionally filtered by service_id / direction_id."""
        hits = [
            {"trip_id": r["trip_id"], "service_id": r.get("service_id", ""),
             "direction_id": r.get("direction_id", "")}
            for r in self.feed.tables.get("trips.txt", [])
            if r.get("route_id") == route_id
            and (service_id is None or r.get("service_id") == service_id)
            and (direction_id is None or r.get("direction_id") == str(direction_id))
        ]
        return {"ok": True, "trips": hits, "count": len(hits)}

    def get_stop_times(self, trip_id: str) -> Dict:
        """Return a trip's stop_times rows, ordered by stop_sequence."""
        rows = [
            {"stop_sequence": r["stop_sequence"], "stop_id": r["stop_id"],
             "arrival_time": r.get("arrival_time", ""),
             "departure_time": r.get("departure_time", "")}
            for r in self.feed.tables.get("stop_times.txt", [])
            if r["trip_id"] == trip_id
        ]
        rows.sort(key=lambda r: int(r["stop_sequence"]))
        return {"ok": True, "trip_id": trip_id, "stop_times": rows, "count": len(rows)}

    # ===== WRITE-SINGLE ==================================================
    def add_stop(self, stop_id: str, stop_name: str, stop_lat: str, stop_lon: str) -> Dict:
        """Create one stop. Fails if stop_id already exists."""
        if self._find_one("stops.txt", "stop_id", stop_id):
            return {"ok": False, "error": f"stop_id {stop_id!r} already exists"}
        row = self.feed.new_row("stops.txt")
        row.update(stop_id=stop_id, stop_name=stop_name,
                   stop_lat=str(stop_lat), stop_lon=str(stop_lon))
        self.feed.table("stops.txt").append(row)
        return {"ok": True, "stop_id": stop_id}

    def update_stop(self, stop_id: str, stop_name: Optional[str] = None,
                    stop_lat: Optional[str] = None, stop_lon: Optional[str] = None,
                    wheelchair_boarding: Optional[str] = None,
                    zone_id: Optional[str] = None) -> Dict:
        """Edit fields of one stop. Only the provided fields change."""
        row = self._find_one("stops.txt", "stop_id", stop_id)
        if row is None:
            return {"ok": False, "error": f"no stop {stop_id!r}"}
        changed = {}
        for col, val in (("stop_name", stop_name), ("stop_lat", stop_lat),
                         ("stop_lon", stop_lon),
                         ("wheelchair_boarding", wheelchair_boarding),
                         ("zone_id", zone_id)):
            if val is not None:
                self.feed.ensure_column("stops.txt", col)
                row[col] = str(val)
                changed[col] = str(val)
        return {"ok": True, "stop_id": stop_id, "changed": changed}

    def delete_stop(self, stop_id: str) -> Dict:
        """Remove a stop. Refuses if any stop_times still reference it."""
        refs = [r for r in self.feed.tables.get("stop_times.txt", [])
                if r["stop_id"] == stop_id]
        if refs:
            return {"ok": False,
                    "error": f"{len(refs)} stop_times still reference {stop_id!r}"}
        before = len(self.feed.tables.get("stops.txt", []))
        self.feed.tables["stops.txt"] = [
            r for r in self.feed.tables.get("stops.txt", []) if r["stop_id"] != stop_id]
        if len(self.feed.tables["stops.txt"]) == before:
            return {"ok": False, "error": f"no stop {stop_id!r}"}
        return {"ok": True, "stop_id": stop_id}

    def update_route(self, route_id: str, route_short_name: Optional[str] = None,
                     route_long_name: Optional[str] = None,
                     route_color: Optional[str] = None,
                     route_text_color: Optional[str] = None,
                     route_desc: Optional[str] = None) -> Dict:
        """Edit fields of one route. Only the provided fields change."""
        row = self._find_one("routes.txt", "route_id", route_id)
        if row is None:
            return {"ok": False, "error": f"no route {route_id!r}"}
        changed = {}
        for col, val in (("route_short_name", route_short_name),
                         ("route_long_name", route_long_name),
                         ("route_color", route_color),
                         ("route_text_color", route_text_color),
                         ("route_desc", route_desc)):
            if val is not None:
                self.feed.ensure_column("routes.txt", col)
                row[col] = str(val)
                changed[col] = str(val)
        return {"ok": True, "route_id": route_id, "changed": changed}

    def update_agency(self, agency_id: str, agency_name: Optional[str] = None,
                      agency_phone: Optional[str] = None,
                      agency_url: Optional[str] = None,
                      agency_timezone: Optional[str] = None) -> Dict:
        """Edit fields of one agency. Only the provided fields change."""
        row = self._find_one("agency.txt", "agency_id", agency_id)
        if row is None:
            return {"ok": False, "error": f"no agency {agency_id!r}"}
        changed = {}
        for col, val in (("agency_name", agency_name), ("agency_phone", agency_phone),
                         ("agency_url", agency_url), ("agency_timezone", agency_timezone)):
            if val is not None:
                self.feed.ensure_column("agency.txt", col)
                row[col] = str(val)
                changed[col] = str(val)
        return {"ok": True, "agency_id": agency_id, "changed": changed}

    def update_frequency(self, trip_id: str, start_time: Optional[str] = None,
                         headway_secs: Optional[str] = None,
                         end_time: Optional[str] = None) -> Dict:
        """Edit a frequencies row. Identify it by trip_id (+ start_time if several)."""
        rows = [r for r in self.feed.tables.get("frequencies.txt", [])
                if r["trip_id"] == trip_id
                and (start_time is None or r.get("start_time") == start_time)]
        if not rows:
            return {"ok": False, "error": f"no frequencies row for trip {trip_id!r}"}
        if len(rows) > 1:
            return {"ok": False,
                    "error": f"{len(rows)} frequencies rows for {trip_id!r}; pass start_time"}
        row = rows[0]
        changed = {}
        if headway_secs is not None:
            row["headway_secs"] = str(headway_secs); changed["headway_secs"] = str(headway_secs)
        if end_time is not None:
            row["end_time"] = end_time; changed["end_time"] = end_time
        return {"ok": True, "trip_id": trip_id, "changed": changed}

    def add_stop_time(self, trip_id: str, stop_id: str, stop_sequence: str,
                      arrival_time: str, departure_time: str) -> Dict:
        """Insert ONE stop_times row. Does NOT renumber or shift anything else."""
        if not self._find_one("trips.txt", "trip_id", trip_id):
            return {"ok": False, "error": f"no trip {trip_id!r}"}
        if not self._find_one("stops.txt", "stop_id", stop_id):
            return {"ok": False, "error": f"no stop {stop_id!r}"}
        row = self.feed.new_row("stop_times.txt")
        row.update(trip_id=trip_id, stop_id=stop_id, stop_sequence=str(stop_sequence),
                   arrival_time=arrival_time, departure_time=departure_time)
        self.feed.table("stop_times.txt").append(row)
        return {"ok": True, "trip_id": trip_id, "stop_sequence": str(stop_sequence)}

    def update_stop_time(self, trip_id: str, stop_sequence: str,
                         arrival_time: Optional[str] = None,
                         departure_time: Optional[str] = None,
                         new_stop_sequence: Optional[str] = None,
                         stop_id: Optional[str] = None) -> Dict:
        """Edit ONE stop_times row, identified by (trip_id, stop_sequence)."""
        row = self._stop_time_row(trip_id, stop_sequence)
        if row is None:
            return {"ok": False, "error": f"no stop_time ({trip_id!r}, seq {stop_sequence})"}
        changed = {}
        if arrival_time is not None:
            row["arrival_time"] = arrival_time; changed["arrival_time"] = arrival_time
        if departure_time is not None:
            row["departure_time"] = departure_time; changed["departure_time"] = departure_time
        if stop_id is not None:
            row["stop_id"] = stop_id; changed["stop_id"] = stop_id
        if new_stop_sequence is not None:
            row["stop_sequence"] = str(new_stop_sequence)
            changed["stop_sequence"] = str(new_stop_sequence)
        return {"ok": True, "trip_id": trip_id, "changed": changed}

    def delete_stop_time(self, trip_id: str, stop_sequence: str) -> Dict:
        """Remove ONE stop_times row. Does NOT renumber remaining rows."""
        row = self._stop_time_row(trip_id, stop_sequence)
        if row is None:
            return {"ok": False, "error": f"no stop_time ({trip_id!r}, seq {stop_sequence})"}
        self.feed.tables["stop_times.txt"].remove(row)
        return {"ok": True, "trip_id": trip_id, "stop_sequence": str(stop_sequence)}

    def add_trip(self, route_id: str, service_id: str, trip_id: str,
                 trip_headsign: Optional[str] = None,
                 direction_id: Optional[str] = None) -> Dict:
        """Create one trip (no stop_times yet). Fails if trip_id already exists."""
        if self._find_one("trips.txt", "trip_id", trip_id):
            return {"ok": False, "error": f"trip_id {trip_id!r} already exists"}
        row = self.feed.new_row("trips.txt")
        row.update(route_id=route_id, service_id=service_id, trip_id=trip_id)
        if trip_headsign is not None:
            row["trip_headsign"] = trip_headsign
        if direction_id is not None:
            row["direction_id"] = str(direction_id)
        self.feed.table("trips.txt").append(row)
        return {"ok": True, "trip_id": trip_id}

    def delete_trip(self, trip_id: str) -> Dict:
        """Remove a trip and ALL of its stop_times rows."""
        if not self._find_one("trips.txt", "trip_id", trip_id):
            return {"ok": False, "error": f"no trip {trip_id!r}"}
        self.feed.tables["trips.txt"] = [
            r for r in self.feed.tables["trips.txt"] if r["trip_id"] != trip_id]
        removed = [r for r in self.feed.tables.get("stop_times.txt", [])
                   if r["trip_id"] == trip_id]
        self.feed.tables["stop_times.txt"] = [
            r for r in self.feed.tables.get("stop_times.txt", []) if r["trip_id"] != trip_id]
        return {"ok": True, "trip_id": trip_id, "stop_times_removed": len(removed)}

    # ===== WRITE-SCOPE (the only set-level ops) ==========================
    def shift_times(self, scope: str, offset_secs: str) -> Dict:
        """Add offset_secs (may be negative) to arrival AND departure for every
        stop_times row matching scope. >24:00 convention preserved. See scope.py."""
        try:
            idxs = scope_mod.resolve_stop_time_indices(self.feed, scope)
        except ValueError as e:
            return {"ok": False, "error": f"bad scope: {e}"}
        offset = int(offset_secs)
        rows = self.feed.tables["stop_times.txt"]
        touched = 0
        for i in idxs:
            r = rows[i]
            for col in ("arrival_time", "departure_time"):
                secs = parse_time(r.get(col))
                if secs is not None:
                    new = secs + offset
                    if new < 0:
                        return {"ok": False,
                                "error": f"shift makes {col} negative on {r['trip_id']}"}
                    r[col] = format_time(new)
            touched += 1
        return {"ok": True, "scope": scope, "rows_shifted": touched}

    def renumber_sequence(self, scope: str) -> Dict:
        """For every trip matching scope, rewrite stop_sequence to 1..n contiguous,
        preserving current order. seq conditions in the scope are ignored here."""
        try:
            trip_ids = scope_mod.resolve_trip_ids(self.feed, scope)
        except ValueError as e:
            return {"ok": False, "error": f"bad scope: {e}"}
        rows = self.feed.tables.get("stop_times.txt", [])
        for tid in trip_ids:
            trip_rows = [r for r in rows if r["trip_id"] == tid]
            trip_rows.sort(key=lambda r: int(r["stop_sequence"]))
            for new_seq, r in enumerate(trip_rows, start=1):
                r["stop_sequence"] = str(new_seq)
        return {"ok": True, "scope": scope, "trips_renumbered": len(trip_ids)}

    # ===== LIFECYCLE =====================================================
    def finish(self) -> Dict:
        """Signal the edit is complete. The executor then runs validation."""
        self.finished = True
        return {"ok": True, "finished": True}


# ---------------------------------------------------------------------------
# Tool schemas — the model's ENTIRE spec for each tool. Written by hand on
# purpose: the descriptions are prompt engineering, not generated metadata.
# ---------------------------------------------------------------------------
def _p(props, required):
    return {"type": "object", "properties": props, "required": required}


_S = lambda d="": {"type": "string", "description": d}
_OPT = lambda d="": {"type": "string", "description": d}

TOOL_SCHEMAS: List[Dict] = [
    # READ
    {"name": "find_stop", "description": "Look up stops by stop_id (exact) or stop_name (case-insensitive substring). Returns matching stop_ids.",
     "parameters": _p({"query": _S("stop name or id")}, ["query"])},
    {"name": "find_route", "description": "Look up routes by route_id or short/long name substring. Returns matching route_ids.",
     "parameters": _p({"query": _S()}, ["query"])},
    {"name": "find_trip", "description": "Look up trips by trip_id or headsign substring, optionally restricted to a route.",
     "parameters": _p({"query": _S(), "route_id": _OPT("restrict to this route")}, ["query"])},
    {"name": "find_agency", "description": "Look up agencies by agency_id or agency_name substring.",
     "parameters": _p({"query": _S()}, ["query"])},
    {"name": "list_trips", "description": "List trip_ids on a route, optionally filtered by service_id and/or direction_id.",
     "parameters": _p({"route_id": _S(), "service_id": _OPT(), "direction_id": _OPT()}, ["route_id"])},
    {"name": "get_stop_times", "description": "Return a trip's stop_times rows (sequence, stop_id, arrival, departure) ordered by stop_sequence.",
     "parameters": _p({"trip_id": _S()}, ["trip_id"])},
    # WRITE-SINGLE
    {"name": "add_stop", "description": "Create ONE stop. Fails if stop_id exists.",
     "parameters": _p({"stop_id": _S(), "stop_name": _S(), "stop_lat": _S(), "stop_lon": _S()},
                      ["stop_id", "stop_name", "stop_lat", "stop_lon"])},
    {"name": "update_stop", "description": "Edit fields of ONE stop (stop_name, stop_lat, stop_lon, wheelchair_boarding, zone_id). Only provided fields change; columns are created if absent.",
     "parameters": _p({"stop_id": _S(), "stop_name": _OPT(), "stop_lat": _OPT(),
                       "stop_lon": _OPT(), "wheelchair_boarding": _OPT("0,1,2"),
                       "zone_id": _OPT()}, ["stop_id"])},
    {"name": "delete_stop", "description": "Remove a stop. Refuses if any stop_times still reference it.",
     "parameters": _p({"stop_id": _S()}, ["stop_id"])},
    {"name": "update_route", "description": "Edit fields of ONE route (short/long name, color, text_color, desc). Only provided fields change.",
     "parameters": _p({"route_id": _S(), "route_short_name": _OPT(), "route_long_name": _OPT(),
                       "route_color": _OPT("6-digit hex, no #"), "route_text_color": _OPT("6-digit hex"),
                       "route_desc": _OPT()}, ["route_id"])},
    {"name": "update_agency", "description": "Edit fields of ONE agency (name, phone, url, timezone). Only provided fields change.",
     "parameters": _p({"agency_id": _S(), "agency_name": _OPT(), "agency_phone": _OPT(),
                       "agency_url": _OPT(), "agency_timezone": _OPT()}, ["agency_id"])},
    {"name": "update_frequency", "description": "Edit a frequencies row (headway_secs, end_time). Identify by trip_id, plus start_time if the trip has several rows.",
     "parameters": _p({"trip_id": _S(), "start_time": _OPT(), "headway_secs": _OPT(),
                       "end_time": _OPT()}, ["trip_id"])},
    {"name": "add_stop_time", "description": "Insert ONE stop_times row. Does NOT renumber later stops or shift other times — you must do that yourself.",
     "parameters": _p({"trip_id": _S(), "stop_id": _S(), "stop_sequence": _S(),
                       "arrival_time": _S("HH:MM:SS, may exceed 24:00:00"),
                       "departure_time": _S("HH:MM:SS")},
                      ["trip_id", "stop_id", "stop_sequence", "arrival_time", "departure_time"])},
    {"name": "update_stop_time", "description": "Edit ONE stop_times row identified by (trip_id, stop_sequence): arrival_time, departure_time, stop_id, or new_stop_sequence.",
     "parameters": _p({"trip_id": _S(), "stop_sequence": _S(), "arrival_time": _OPT(),
                       "departure_time": _OPT(), "new_stop_sequence": _OPT(), "stop_id": _OPT()},
                      ["trip_id", "stop_sequence"])},
    {"name": "delete_stop_time", "description": "Remove ONE stop_times row (trip_id, stop_sequence). Does NOT renumber the remaining rows.",
     "parameters": _p({"trip_id": _S(), "stop_sequence": _S()}, ["trip_id", "stop_sequence"])},
    {"name": "add_trip", "description": "Create ONE trip with no stop_times yet. Fails if trip_id exists.",
     "parameters": _p({"route_id": _S(), "service_id": _S(), "trip_id": _S(),
                       "trip_headsign": _OPT(), "direction_id": _OPT("0 or 1")},
                      ["route_id", "service_id", "trip_id"])},
    {"name": "delete_trip", "description": "Remove a trip AND all of its stop_times rows.",
     "parameters": _p({"trip_id": _S()}, ["trip_id"])},
    # WRITE-SCOPE
    {"name": "shift_times", "description": "Add offset_secs (may be negative) to arrival AND departure for every stop_times row matching scope. Scope grammar: field op value [AND ...], fields=route|service|trip|direction|seq, e.g. 'service=FULLW' or 'trip=CITY1 AND seq>4'.",
     "parameters": _p({"scope": _S("selector, e.g. service=FULLW"),
                       "offset_secs": _S("integer seconds, may be negative")},
                      ["scope", "offset_secs"])},
    {"name": "renumber_sequence", "description": "For every trip matching scope, rewrite stop_sequence to 1..n contiguous, preserving order. Same scope grammar as shift_times (seq conditions ignored here).",
     "parameters": _p({"scope": _S("selector, e.g. route=CITY")}, ["scope"])},
    # LIFECYCLE
    {"name": "finish", "description": "Call when the requested edit is fully complete. Triggers validation.",
     "parameters": _p({}, [])},
]

TOOL_NAMES = [t["name"] for t in TOOL_SCHEMAS]
