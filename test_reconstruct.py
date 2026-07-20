"""Verify reconstruct-from-storage without Supabase or the LLM (LocalDiskStorage)."""
import tempfile
from gtfs_tools import Feed, MockClient
from server.storage import LocalDiskStorage
from server.sessions import SessionStore

client = MockClient(lambda m: None)  # never actually called here

with tempfile.TemporaryDirectory() as root:
    store = SessionStore(client, LocalDiskStorage(root))
    sid = store.create(Feed.load("data/sample-feed"))

    chat = store.get(sid)
    # simulate an applied edit + a couple of conversation turns
    chat.history += [{"role": "user", "text": "rename stagecoach"},
                     {"role": "assistant", "text": "done"}]
    for r in chat.feed.tables["stops.txt"]:
        if r["stop_id"] == "STAGECOACH":
            r["stop_name"] = "Renamed Stop"
    store.persist(sid)

    store._sessions.clear()            # <-- simulate Render spin-down (memory wiped)

    chat2 = store.get(sid)             # must rebuild from disk, not return None
    assert chat2 is not None, "reconstruction returned None"
    cur = next(r["stop_name"] for r in chat2.feed.tables["stops.txt"] if r["stop_id"] == "STAGECOACH")
    orig = next(r["stop_name"] for r in chat2.original.tables["stops.txt"] if r["stop_id"] == "STAGECOACH")
    print("history turns:", len(chat2.history))
    print("current name :", cur)
    print("original name:", orig)
    print("pending diff :", chat2.pending_changes())

    assert cur == "Renamed Stop", "current feed edit lost"
    assert orig != "Renamed Stop", "original feed corrupted"
    assert len(chat2.history) == 2, "history lost"
    assert chat2.pending_changes(), "diff-vs-original lost"
    print("\nOK — session reconstructed from storage after simulated spin-down")
