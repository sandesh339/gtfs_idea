"""Interactive GTFS editing chatbot (CLI) — the proof-of-concept, local edition.

Loads a feed, then routes each plain-English instruction to function calling,
code generation, or a clarifying question, applying successful edits to a
persistent session feed.

Usage:
  python chatbot.py                     # uses data/sample-feed
  python chatbot.py --feed path/to/gtfs

Commands inside the chat:
  /feed            show the current feed summary
  /diff            show all changes since the feed was loaded
  /undo            revert the last applied edit
  /reset           reload the original feed
  /save <dir>      write the current feed to <dir>
  /help            list commands
  /quit            exit
"""
import argparse
import os
import sys

try:  # GTFS names may be UTF-8; keep a Windows cp1252 console from crashing
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from dotenv import load_dotenv

from gtfs_tools import Feed
from gtfs_tools.chat import ChatSession
from gtfs_tools.llm import OpenAIClient

BANNER = """GTFS editing chatbot — describe an edit in plain English.
The router decides how to handle it (function calling / code generation / ask).
Type /help for commands, /quit to exit.
"""


def render(resp) -> None:
    d = resp.decision
    if d is not None:
        print(f"  [router] tool_fit={d.tool_fit} conf={d.confidence:.2f} "
              f"-> {d.path}  ({d.reason})")
    if resp.kind == "clarify":
        print(f"  [?] {resp.text}")
    elif resp.kind == "applied":
        c = resp.cost
        print(f"  [done] {resp.text}  (calls={c.get('calls')}, repairs={c.get('repairs')})")
        for line in resp.changes:
            print(f"      {line}")
    else:  # failed
        print(f"  [fail] {resp.text}")


def handle_command(session: ChatSession, line: str) -> bool:
    """Return False if the command is /quit."""
    parts = line.split()
    cmd = parts[0].lower()
    if cmd in ("/quit", "/exit"):
        return False
    if cmd == "/help":
        print("  /feed  /diff  /undo  /reset  /save <dir>  /quit")
    elif cmd == "/feed":
        print("  " + session.feed_summary())
    elif cmd == "/diff":
        changes = session.pending_changes()
        print("  no changes yet" if not changes else
              "\n".join(f"  {c}" for c in changes))
    elif cmd == "/undo":
        print("  reverted last edit" if session.undo() else "  nothing to undo")
    elif cmd == "/reset":
        session.reset()
        print("  feed reset to original")
    elif cmd == "/save":
        if len(parts) < 2:
            print("  usage: /save <dir>")
        else:
            session.save(parts[1])
            print(f"  saved to {parts[1]}")
    else:
        print(f"  unknown command {cmd}; /help for the list")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--feed", default=os.path.join("data", "sample-feed"))
    args = ap.parse_args()

    load_dotenv(override=True)
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        print("ERROR: set OPENAI_API_KEY in .env", file=sys.stderr)
        return 1
    client = OpenAIClient(model=os.getenv("OPENAI_MODEL", "gpt-5.5"), api_key=key,
                          base_url=os.getenv("OPENAI_BASE_URL"))

    feed = Feed.load(args.feed)
    session = ChatSession(feed, client)

    print(BANNER)
    print("Loaded: " + session.feed_summary() + "\n")

    while True:
        try:
            line = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line.startswith("/"):
            if not handle_command(session, line):
                break
            continue
        try:
            resp = session.handle(line)
            render(resp)
        except Exception as e:  # keep the REPL alive
            print(f"  ! error: {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
