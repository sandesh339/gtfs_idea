"""Build a very small, valid GTFS slice (1-2 routes) with real shapes.txt
geometry, for the LIVE CHATBOT'S demo session (server/app.py DEMO_FEED_DIR).

This is separate from data/sample-feed, which stays untouched: that feed is
load-bearing for the benchmark/oracle (gtfs_tools/scenarios.py hardcodes
entities like CITY, CITY1, FULLW, AAMV that only exist in it).

Usage: python make_small_demo_feed.py <src_dir> <out_dir> <route_id> [route_id ...]
"""
import os
import sys

from gtfs_tools import Feed


def reduce_to_routes(src_dir: str, route_ids: list, out_dir: str) -> None:
    f = Feed.load(src_dir)
    route_ids = set(route_ids)
    trips = [t for t in f.tables["trips.txt"] if t["route_id"] in route_ids]
    trip_ids = {t["trip_id"] for t in trips}
    stop_times = [st for st in f.tables.get("stop_times.txt", []) if st["trip_id"] in trip_ids]

    stop_ids = {st["stop_id"] for st in stop_times}
    stops_by_id = {s["stop_id"]: s for s in f.tables["stops.txt"]}
    for sid in list(stop_ids):
        p = stops_by_id.get(sid, {}).get("parent_station")
        if p:
            stop_ids.add(p)
    stops = [s for s in f.tables["stops.txt"] if s["stop_id"] in stop_ids]

    service_ids = {t["service_id"] for t in trips}
    calendar = [c for c in f.tables.get("calendar.txt", []) if c["service_id"] in service_ids]
    calendar_dates = [c for c in f.tables.get("calendar_dates.txt", [])
                       if c["service_id"] in service_ids]

    shape_ids = {t["shape_id"] for t in trips if t.get("shape_id")}
    shapes = [s for s in f.tables.get("shapes.txt", []) if s.get("shape_id") in shape_ids]

    routes = [r for r in f.tables["routes.txt"] if r["route_id"] in route_ids]

    out = Feed()
    out.headers = dict(f.headers)
    out.tables["agency.txt"] = f.tables.get("agency.txt", [])
    out.tables["routes.txt"] = routes
    out.tables["trips.txt"] = trips
    out.tables["stop_times.txt"] = stop_times
    out.tables["stops.txt"] = stops
    if calendar:
        out.tables["calendar.txt"] = calendar
    if calendar_dates:
        out.tables["calendar_dates.txt"] = calendar_dates
    if shapes:
        out.tables["shapes.txt"] = shapes
    if f.tables.get("feed_info.txt"):
        out.tables["feed_info.txt"] = f.tables["feed_info.txt"]

    out.save(out_dir)
    print(f"{sorted(route_ids)}: {len(routes)} routes, {len(trips)} trips, "
          f"{len(stop_times)} stop_times rows, {len(stops)} stops, "
          f"{len(shapes)} shape points -> {out_dir}")


if __name__ == "__main__":
    src, out_dir = sys.argv[1], sys.argv[2]
    route_ids = sys.argv[3:]
    reduce_to_routes(src, route_ids, out_dir)
