"""Quick sanity check of the tool collection against the real sample feed."""
import tempfile, os
from gtfs_tools import Feed, GTFSToolkit, TOOL_SCHEMAS

FEED_DIR = os.path.join("data", "sample-feed")

feed = Feed.load(FEED_DIR)
tk = GTFSToolkit(feed)

print(f"loaded {len(TOOL_SCHEMAS)} tools; tables: {sorted(feed.tables)}\n")

# --- R1 (HIGH tool-fit): rename a stop in one find + one update -----------
m = tk.find_stop("Stagecoach Hotel")
print("find_stop ->", m)
sid = m["matches"][0]["stop_id"]
print("update_stop ->", tk.update_stop(sid, stop_name="Stagecoach Casino"))

# --- R5 (HIGH): wheelchair flag on a column that does not exist yet --------
bf = tk.find_stop("Bullfrog")["matches"][0]["stop_id"]
print("update_stop (new col) ->", tk.update_stop(bf, wheelchair_boarding="1"))

# --- S5 (LOW, but its core is one scope op): push FULLW service +15 min ----
before = tk.get_stop_times("AB1")["stop_times"][0]
print("\nAB1 first stop before:", before["departure_time"])
print("shift_times ->", tk.shift_times("service=FULLW", str(15 * 60)))
after = tk.get_stop_times("AB1")["stop_times"][0]
print("AB1 first stop after :", after["departure_time"])

# --- scope precision: a single trip + seq filter --------------------------
print("\nshift one trip's tail:", tk.shift_times("trip=CITY1 AND seq>2", "60"))

# --- renumber after a hypothetical delete ---------------------------------
tk.delete_stop_time("CITY1", "2")
print("renumber_sequence ->", tk.renumber_sequence("trip=CITY1"))
print("CITY1 seqs now:", [r["stop_sequence"] for r in tk.get_stop_times("CITY1")["stop_times"]])

# --- round-trip save/reload -----------------------------------------------
with tempfile.TemporaryDirectory() as d:
    feed.save(d)
    reloaded = Feed.load(d)
    name = next(r["stop_name"] for r in reloaded.tables["stops.txt"] if r["stop_id"] == sid)
    print("\nround-trip rename persisted:", name)
    print("wheelchair col persisted:", "wheelchair_boarding" in reloaded.headers["stops.txt"])

print("\nfinish ->", tk.finish())
