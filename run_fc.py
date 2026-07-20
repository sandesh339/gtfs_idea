"""Run the function-calling path on a single request, with GPT.

Usage:
  python run_fc.py "Rename the stop 'Stagecoach Hotel & Casino' to 'Stagecoach Casino'."
  python run_fc.py --feed data/sample-feed --out out/edited "<request>"

Reads OPENAI_API_KEY / OPENAI_MODEL from .env.
"""
import argparse
import os
import sys

from dotenv import load_dotenv

from gtfs_tools import Feed
from gtfs_tools.executor import ReActExecutor
from gtfs_tools.llm import OpenAIClient


def feed_metadata(feed: Feed) -> str:
    routes = ", ".join(r["route_id"] for r in feed.tables.get("routes.txt", []))
    n_stops = len(feed.tables.get("stops.txt", []))
    n_trips = len(feed.tables.get("trips.txt", []))
    return f"routes: {routes} | {n_stops} stops | {n_trips} trips"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("request")
    ap.add_argument("--feed", default=os.path.join("data", "sample-feed"))
    ap.add_argument("--out", default=None, help="dir to save the edited feed")
    ap.add_argument("--repair-rounds", type=int, default=3)
    args = ap.parse_args()

    load_dotenv(override=True)  # .env is the source of truth, beats stale shell vars
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        print("ERROR: set OPENAI_API_KEY in .env", file=sys.stderr)
        return 1
    model = os.getenv("OPENAI_MODEL", "gpt-5.5")
    client = OpenAIClient(model=model, api_key=key, base_url=os.getenv("OPENAI_BASE_URL"))

    feed = Feed.load(args.feed)
    executor = ReActExecutor(client, repair_rounds=args.repair_rounds)

    print(f"model: {client.name}")
    print(f"request: {args.request}\n")
    result = executor.run(feed, args.request, feed_metadata(feed))

    for i, s in enumerate(result.steps, 1):
        print(f"  {i:>2}. {s.name}({_fmt(s.arguments)}) -> {_fmt(s.result)}")
    print(f"\nsuccess={result.success}  calls={result.num_calls}  "
          f"repairs={result.repair_rounds_used}  reason={result.stop_reason}")
    if result.validation_errors:
        print("validation errors:", result.validation_errors)

    if args.out:
        feed.save(args.out)
        print(f"edited feed written to {args.out}")
    return 0 if result.success else 2


def _fmt(d: dict) -> str:
    s = str(d)
    return s if len(s) <= 120 else s[:117] + "..."


if __name__ == "__main__":
    raise SystemExit(main())
