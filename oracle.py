"""Stage-2 correctness oracle for the MBTA benchmark.

For each scenario, a checker verifies the INTENDED edit actually happened (not
merely that *some* valid change occurred). Each returns Check(ok, reason).

check(sid, pristine, edited, changed) -> Check
  ok = True/False  (None if no oracle registered for that scenario)

Checkers verify the necessary intended property. They are deliberately lenient
about *how* an edit is achieved but strict about the observable outcome, so a
mechanism that does the wrong thing fails even if it produced a valid feed.
"""
from collections import namedtuple, defaultdict

from gtfs_tools.diffing import summarize_changes

Check = namedtuple("Check", "ok reason")
CHECKS = {}


def check(sid):
    def deco(fn):
        CHECKS[sid] = fn
        return fn
    return deco


def run_check(sid, pristine, edited, changed):
    fn = CHECKS.get(sid)
    if fn is None:
        return Check(None, "no oracle")
    try:
        return fn(pristine, edited, changed)
    except Exception as ex:  # a buggy checker must never crash a run
        return Check(False, f"oracle error: {type(ex).__name__}: {ex}")


# ---------------- helpers ----------------
def _sec(t):
    if not t:
        return None
    try:
        h, m, s = t.split(":")
        return int(h) * 3600 + int(m) * 60 + int(s)
    except (ValueError, AttributeError):
        return None


def _stops(f):
    return f.tables.get("stops.txt", [])


def _named(f, name):
    return [s for s in _stops(f) if s.get("stop_name") == name]


def _route(f, rid):
    return next((r for r in f.tables.get("routes.txt", []) if r.get("route_id") == rid), None)


def _routes_named(f, name):
    return [r for r in f.tables.get("routes.txt", []) if r.get("route_long_name") == name]


def _trips(f, rid):
    return [t for t in f.tables.get("trips.txt", []) if t.get("route_id") == rid]


def _tripset(f, rid):
    return {t["trip_id"] for t in _trips(f, rid)}


def _cal(f, sid):
    return next((c for c in f.tables.get("calendar.txt", []) if c.get("service_id") == sid), None)


def _st(f):
    d = defaultdict(list)
    for r in f.tables.get("stop_times.txt", []):
        d[r["trip_id"]].append(r)
    for k in d:
        d[k].sort(key=lambda r: int(float(r["stop_sequence"])))
    return d


def _stopname_map(f):
    return {s["stop_id"]: s.get("stop_name", "") for s in _stops(f)}


def _yes(v):
    return str(v).strip() == "1"


# ---------------- Group A: stop attributes ----------------
@check("A1")
def a1(p, e, ch):
    pn = {s["stop_id"] for s in _named(p, "Nubian")}
    renamed = [s for s in _stops(e) if s["stop_id"] in pn and s.get("stop_name") == "Nubian Square"]
    return Check(len(renamed) == len(pn) and pn != set(),
                 f"{len(renamed)}/{len(pn)} 'Nubian' stops renamed to 'Nubian Square'")


@check("A2")
def a2(p, e, ch):
    m = {s["stop_id"]: s for s in _named(e, "Massachusetts Ave @ Wendell St")}
    # the stop may have been renamed? match by pristine id
    pid = [s["stop_id"] for s in _named(p, "Massachusetts Ave @ Wendell St")]
    em = {s["stop_id"]: s for s in _stops(e)}
    for sid in pid:
        s = em.get(sid)
        if s and abs(float(s.get("stop_lat", 0) or 0) - 42.3888) < 1e-3 and abs(float(s.get("stop_lon", 0) or 0) + 71.1152) < 1e-3:
            return Check(True, "Wendell St stop moved to target coord")
    return Check(False, "Wendell St stop not at target coordinate")


@check("A3")
def a3(p, e, ch):
    st = _named(e, "Massachusetts Ave @ Inman St")
    ok = st and all(_yes(s.get("wheelchair_boarding")) for s in st)
    return Check(bool(ok), "Inman St stop marked wheelchair accessible" if ok else "wheelchair_boarding not set")


@check("A4")
def a4(p, e, ch):
    st = _named(e, "Sharon")
    ok = st and all(s.get("zone_id") == "CR-zone-9" for s in st)
    return Check(bool(ok), "Sharon zone_id set to CR-zone-9" if ok else "zone_id not set on all 'Sharon'")


@check("A5")
def a5(p, e, ch):
    st = _named(e, "Wollaston")
    ok = any("Elevator to the inbound platform." in (s.get("stop_desc") or "") for s in st)
    return Check(ok, "Wollaston stop_desc set" if ok else "description not found on Wollaston")


@check("A6")
def a6(p, e, ch):
    st = _named(e, "Harvard Avenue")
    ok = any(s.get("stop_code") == "GB-HAV" for s in st)
    return Check(ok, "Harvard Avenue stop_code=GB-HAV" if ok else "stop_code not set")


# ---------------- Group B: route/agency branding ----------------
@check("B1")
def b1(p, e, ch):
    r = _route(e, "66")
    ok = r and (r.get("route_color", "").upper() == "1E90FF") and (r.get("route_text_color", "").upper() == "FFFFFF")
    return Check(bool(ok), "route 66 colour/text set" if ok else f"colours={r and (r.get('route_color'), r.get('route_text_color'))}")


@check("B2")
def b2(p, e, ch):
    r = _route(e, "39")
    ok = r and r.get("route_long_name") == "Forest Hills - Back Bay via Huntington"
    return Check(bool(ok), "route 39 long name set" if ok else "long name not set")


@check("B3")
def b3(p, e, ch):
    r = _route(e, "111")
    return Check(bool(r and r.get("route_short_name") == "111X"), "route 111 short name = 111X")


@check("B4")
def b4(p, e, ch):
    ags = e.tables.get("agency.txt", [])
    ok = any((a.get("agency_phone") or "").replace(" ", "") == "(617)222-3200" for a in ags)
    return Check(ok, "agency phone set" if ok else "phone not set")


@check("B5")
def b5(p, e, ch):
    ags = e.tables.get("agency.txt", [])
    ok = any(a.get("agency_url") == "https://www.mbta.com" for a in ags)
    return Check(ok, "agency url set" if ok else "url not set")


@check("B6")
def b6(p, e, ch):
    r = _route(e, "77")
    return Check(bool(r and r.get("route_url") == "https://www.mbta.com/schedules/77/timetable"), "route 77 route_url set")


# ---------------- Group C: service/calendar ----------------
@check("C1")
def c1(p, e, ch):
    c = _cal(e, "BUS20263-hba36011-Weekday-02")
    return Check(bool(c and _yes(c.get("saturday"))), "weekday service now runs Saturdays")


@check("C2")
def c2(p, e, ch):
    c = _cal(e, "BUS20263-hbc36017-Sunday-02")
    return Check(bool(c and not _yes(c.get("sunday"))), "Sunday service no longer runs Sundays")


@check("C3")
def c3(p, e, ch):
    c = _cal(e, "BUS20263-hbc36sn1-Weekday-02")
    return Check(bool(c and c.get("end_date") == "20260815"), "service end_date = 20260815")


@check("C4")
def c4(p, e, ch):
    cd = e.tables.get("calendar_dates.txt", [])
    ok = any(r.get("service_id") == "DIV20263-hmo36ct1-Weekday-01" and r.get("date") == "20260525"
             and str(r.get("exception_type")) == "2" for r in cd)
    return Check(ok, "no-service exception added" if ok else "exception row not found")


@check("C5")
def c5(p, e, ch):
    pt, et = _tripset(p, "39"), _tripset(e, "39")
    removed = pt - et
    if len(removed) != 1:
        return Check(False, f"{len(removed)} route-39 trips removed (want exactly 1)")
    tid = next(iter(removed))
    if any(r["trip_id"] == tid for r in e.tables.get("stop_times.txt", [])):
        return Check(False, "trip removed but stop_times remain")
    pst = _st(p)
    fd = lambda t: (_sec(pst[t][0].get("departure_time")) if pst.get(t) else None)
    others = [fd(t) for t in pt if t != tid and fd(t) is not None]
    latest = fd(tid) is not None and (not others or fd(tid) >= max(others))
    return Check(latest, f"removed latest-departing route-39 trip {tid}" if latest else "removed trip was not the latest")


@check("C6")
def c6(p, e, ch):
    added = _tripset(e, "77") - _tripset(p, "77")
    if not added:
        return Check(False, "no new route-77 trip added")
    est = _st(e)
    for tid in added:
        rows = est.get(tid, [])
        if rows and _sec(rows[0].get("departure_time")) == _sec("09:00:00") and len(rows) >= 20:
            return Check(True, f"new 09:00 route-77 trip with {len(rows)} stops")
    return Check(False, "new trip but not departing 09:00 with a full pattern")


# ---------------- Group D: timetable / travel-time ----------------
def _shifted_by(p, e, tids, delta, cols=("arrival_time", "departure_time")):
    pst, est = _st(p), _st(e)
    checked = 0
    for tid in tids:
        er = {r["stop_sequence"]: r for r in est.get(tid, [])}
        for prow in pst.get(tid, []):
            erow = er.get(prow["stop_sequence"])
            if not erow:
                return False, f"trip {tid} seq {prow['stop_sequence']} missing"
            for col in cols:
                a, b = _sec(prow.get(col)), _sec(erow.get(col))
                if a is None or b is None:
                    continue
                if b - a != delta:
                    return False, f"trip {tid} {col} shifted {b - a}s (want {delta})"
                checked += 1
    return checked > 0, f"{len(tids)} trips shifted {delta:+d}s"


@check("D1")
def d1(p, e, ch):
    tids = {t["trip_id"] for t in p.tables["trips.txt"] if t.get("service_id") == "DIV20263-hms36pk1-Weekday-01"}
    if not tids:
        return Check(False, "no trips on service")
    ok, why = _shifted_by(p, e, tids, 900)
    return Check(ok, why)


@check("D3")
def d3(p, e, ch):
    # every Orange trip: +120s from the Downtown Crossing stop onward
    orange = _tripset(p, "Orange")
    pn = _stopname_map(p)
    pst, est = _st(p), _st(e)
    ok_any = False
    for tid in orange:
        prows = pst.get(tid, [])
        idx = next((i for i, r in enumerate(prows) if pn.get(r["stop_id"]) == "Downtown Crossing"), None)
        if idx is None:
            continue
        er = {r["stop_sequence"]: r for r in est.get(tid, [])}
        # stop after DTX should be +120
        if idx + 1 < len(prows):
            nxt = prows[idx + 1]
            a, b = _sec(nxt.get("arrival_time")), _sec(er.get(nxt["stop_sequence"], {}).get("arrival_time"))
            if a is not None and b is not None:
                if b - a != 120:
                    return Check(False, f"trip {tid} downstream shift {b - a}s (want 120)")
                ok_any = True
    return Check(ok_any, "Orange trips: +2min dwell propagated downstream from Downtown Crossing")


@check("D4")
def d4(p, e, ch):
    gb = _tripset(p, "Green-B")
    pn = _stopname_map(p)
    pst, est = _st(p), _st(e)
    ok_any = False
    for tid in gb:
        prows = pst.get(tid, [])
        i1 = next((i for i, r in enumerate(prows) if pn.get(r["stop_id"]) == "Packard's Corner"), None)
        i2 = next((i for i, r in enumerate(prows) if pn.get(r["stop_id"]) == "Harvard Avenue"), None)
        if i1 is None or i2 is None or i2 <= i1:
            continue
        er = {r["stop_sequence"]: r for r in est.get(tid, [])}
        a1 = _sec(prows[i2].get("arrival_time")); b1 = _sec(er.get(prows[i2]["stop_sequence"], {}).get("arrival_time"))
        if a1 is not None and b1 is not None:
            if b1 - a1 != -60:
                return Check(False, f"trip {tid} arrival at Harvard Ave shifted {b1 - a1}s (want -60)")
            ok_any = True
    return Check(ok_any, "Green-B: segment sped up 1 min, downstream pulled earlier")


@check("D5")
def d5(p, e, ch):
    if not _named(e, "Mass Ave @ Marlborough St"):
        return Check(False, "new stop not created")
    r1 = _tripset(p, "1")
    pst, est = _st(p), _st(e)
    grew = sum(1 for t in r1 if len(est.get(t, [])) == len(pst.get(t, [])) + 1)
    return Check(grew > 0, f"{grew} route-1 trips gained the inserted stop")


@check("D6")
def d6(p, e, ch):
    r1 = _tripset(p, "1")
    pn, en = _stopname_map(p), _stopname_map(e)
    pst, est = _st(p), _st(e)
    still = 0
    for t in r1:
        if any(en.get(r["stop_id"]) == "Massachusetts Ave @ Sidney St" for r in est.get(t, [])):
            still += 1
    return Check(still == 0, "Sidney St removed from all route-1 trips" if still == 0 else f"{still} route-1 trips still serve Sidney St")


@check("D7")
def d7(p, e, ch):
    r39 = _tripset(p, "39")
    pst, est = _st(p), _st(e)
    aft = [t for t in r39 if pst.get(t) and _sec(pst[t][0].get("departure_time")) is not None and _sec(pst[t][0]["departure_time"]) > _sec("15:00:00")]
    mor = [t for t in r39 if t not in aft]
    ok_a, _ = _shifted_by(p, e, aft, -600)
    ok_m, _ = _shifted_by(p, e, mor, 0)
    return Check(ok_a and ok_m, f"afternoon route-39 trips -10min ({len(aft)}), morning unchanged ({len(mor)})")


@check("D8")
def d8(p, e, ch):
    r77 = _tripset(p, "77")
    pst, est = _st(p), _st(e)
    for tid in r77:
        prows, erows = pst.get(tid, []), {r["stop_sequence"]: r for r in est.get(tid, [])}
        for i, prow in enumerate(prows):
            a, b = _sec(prow.get("departure_time")), _sec(erows.get(prow["stop_sequence"], {}).get("departure_time"))
            if a is None or b is None:
                continue
            if b - a != 60 * i:
                return Check(False, f"trip {tid} stop {i} cumulative shift {b - a}s (want {60 * i})")
        return Check(True, "route-77 cumulative +1min per segment")
    return Check(False, "no route-77 trips checked")


# ---------------- Group E: topology ----------------
@check("E1")
def e1(p, e, ch):
    p1 = [t for t in _trips(p, "111") if str(t.get("direction_id")) == "1"]
    e1_ = [t for t in _trips(e, "111") if str(t.get("direction_id")) == "1"]
    return Check(len(e1_) > len(p1), f"route-111 direction=1 trips {len(p1)} -> {len(e1_)}")


@check("E2")
def e2(p, e, ch):
    ok = bool(_routes_named(e, "Orange North") and _routes_named(e, "Orange South"))
    return Check(ok, "routes 'Orange North' and 'Orange South' created" if ok else "split routes not found")


@check("E3")
def e3(p, e, ch):
    et = {t["trip_id"] for t in e.tables.get("trips.txt", [])}
    a, b = "76328279" in et, "76328280" in et
    if a == b:
        return Check(False, "expected exactly one of the two trips to remain")
    kept = "76328279" if a else "76328280"
    est = _st(e)
    pst = _st(p)
    grew = len(est.get(kept, [])) > max(len(pst.get("76328279", [])), len(pst.get("76328280", [])))
    return Check(grew, f"merged into {kept} ({len(est.get(kept, []))} stops)")


@check("E4")
def e4(p, e, ch):
    ok = bool(_named(e, "Heights Loop North") and _named(e, "Heights Loop South"))
    r77 = _tripset(p, "77")
    pst, est = _st(p), _st(e)
    ext = sum(1 for t in r77 if len(est.get(t, [])) >= len(pst.get(t, [])) + 2)
    return Check(ok and ext > 0, f"2 new terminal stops; {ext} route-77 trips extended")


@check("E5")
def e5(p, e, ch):
    r = _route(e, "XCE")
    if not r:
        return Check(False, "route XCE not created")
    trips = _tripset(e, "XCE")
    return Check(len(trips) > 0, f"route XCE with {len(trips)} trip(s)")


@check("E6")
def e6(p, e, ch):
    est = _st(e)
    bad = 0
    tot = 0
    for tid, rows in est.items():
        tot += 1
        seqs = [int(float(r["stop_sequence"])) for r in rows]
        if seqs != list(range(1, len(seqs) + 1)):
            bad += 1
    return Check(bad == 0 and tot > 0, f"{tot - bad}/{tot} trips renumbered 1..n contiguous")


@check("E7")
def e7(p, e, ch):
    pst, est = _st(p), _st(e)
    base = est.get("78493439") or pst.get("78493439")
    n = len(base)
    sat = {c["service_id"] for c in e.tables.get("calendar.txt", []) if _yes(c.get("saturday")) and not _yes(c.get("monday"))}
    added = {t["trip_id"] for t in e.tables.get("trips.txt", [])} - {t["trip_id"] for t in p.tables.get("trips.txt", [])}
    for tid in added:
        t = next((x for x in e.tables["trips.txt"] if x["trip_id"] == tid), None)
        if t and len(est.get(tid, [])) == n and (t.get("service_id") in sat):
            return Check(True, f"cloned trip {tid} as Saturday-only")
    return Check(False, "no Saturday-only clone of 78493439's pattern")


@check("E8")
def e8(p, e, ch):
    en = _stopname_map(e)
    est = _st(e)
    rows = est.get("76676011", [])
    if not rows:
        return Check(False, "trip 76676011 missing")
    has = any(en.get(r["stop_id"]) == "Massachusetts Ave @ Sidney St" for r in rows)
    seqs = [int(float(r["stop_sequence"])) for r in rows]
    contig = seqs == list(range(1, len(seqs) + 1))
    return Check(not has and contig, "Sidney St skipped and sequence contiguous" if not has else "Sidney St still on trip")


# ---------------- Group F: under-specified -> correct = refrained ----------------
def _refrained(p, e, ch):
    return Check(not ch, "correctly made no edit" if not ch else "edited an under-specified request")


for _f in ("F1", "F2", "F3", "F4", "F5", "F6"):
    CHECKS[_f] = _refrained
