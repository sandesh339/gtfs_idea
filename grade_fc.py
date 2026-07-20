"""Run the FC mechanism on a scenario (or all) and grade the result.

Usage:
  python grade_fc.py R1            # one scenario
  python grade_fc.py all           # every scenario in the registry
  python grade_fc.py R1 --no-llm   # grade a pre-saved feed in out/<id> without re-running

Reads OPENAI_API_KEY / OPENAI_MODEL from .env.
"""
import argparse
import os
import sys

from dotenv import load_dotenv

from gtfs_tools import Feed
from gtfs_tools.executor import ReActExecutor
from gtfs_tools.llm import OpenAIClient
from gtfs_tools.scenarios import SCENARIOS
from gtfs_tools.grader import grade
from gtfs_tools.integrity import validate_feed

FEED_DIR = os.path.join("data", "sample-feed")


def run_and_grade(scenario, client, save_dir=None, validator=validate_feed):
    original = Feed.load(FEED_DIR)      # pristine, for grading
    edit_feed = Feed.load(FEED_DIR)     # mutated by the run
    executor = ReActExecutor(client)
    result = executor.run(edit_feed, scenario.request)
    if save_dir:
        edit_feed.save(save_dir)
    cost = {"calls": result.num_calls, "repairs": result.repair_rounds_used,
            "structural_success": result.success}
    return grade(scenario, original, edit_feed, cost, validator=validator)


def grade_saved(scenario, out_dir, validator=validate_feed):
    original = Feed.load(FEED_DIR)
    edited = Feed.load(out_dir)
    return grade(scenario, original, edited,
                 cost={"calls": "-", "repairs": "-", "structural_success": "-"},
                 validator=validator)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario", help="scenario id or 'all'")
    ap.add_argument("--no-llm", action="store_true", help="grade pre-saved out/<id> feed")
    ap.add_argument("--official", action="store_true",
                    help="use the official GTFS validator for the validity dimension")
    args = ap.parse_args()

    ids = list(SCENARIOS) if args.scenario == "all" else [args.scenario.upper()]
    for sid in ids:
        if sid not in SCENARIOS:
            print(f"unknown scenario {sid}; known: {list(SCENARIOS)}", file=sys.stderr)
            return 1

    validator = validate_feed
    if args.official:
        from gtfs_tools.gtfs_validator import OfficialValidator
        jar = os.getenv("GTFS_VALIDATOR_JAR", os.path.join("vendor", "gtfs-validator-cli.jar"))
        print("setting official-validator baseline (one validator run) ...", file=sys.stderr)
        validator = OfficialValidator(jar).set_baseline(Feed.load(FEED_DIR)).validate

    client = None
    if not args.no_llm:
        load_dotenv(override=True)
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            print("ERROR: set OPENAI_API_KEY in .env", file=sys.stderr)
            return 1
        client = OpenAIClient(model=os.getenv("OPENAI_MODEL", "gpt-5.5"), api_key=key,
                              base_url=os.getenv("OPENAI_BASE_URL"))

    reports = []
    for sid in ids:
        scenario = SCENARIOS[sid]
        if args.no_llm:
            report = grade_saved(scenario, os.path.join("out", sid.lower()), validator=validator)
        else:
            print(f"running {sid} ...", file=sys.stderr)
            report = run_and_grade(scenario, client, save_dir=os.path.join("out", sid.lower()),
                                   validator=validator)
        reports.append(report)
        print(report.render())
        print()

    n_pass = sum(r.overall_pass for r in reports)
    print(f"=== {n_pass}/{len(reports)} scenarios pass overall ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
