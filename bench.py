"""Unified benchmark runner — run a mechanism on a scenario (or all) and grade.

Usage:
  python bench.py R1                          # FC (default), lightweight validity
  python bench.py all --mechanism codegen     # code-gen path
  python bench.py all --mechanism fc --official
  python bench.py S1 --mechanism codegen --official

Runs both mechanisms through the SAME grader, so the reports are directly
comparable (the FC-vs-codegen head-to-head). Edited feeds saved to
out/<mechanism>/<id>. Reads OPENAI_API_KEY / OPENAI_MODEL from .env.
"""
import argparse
import os
import sys

from dotenv import load_dotenv

from gtfs_tools import Feed, ReActExecutor, CodeGenExecutor, OpenAIClient
from gtfs_tools.scenarios import SCENARIOS
from gtfs_tools.grader import grade
from gtfs_tools.integrity import validate_feed

FEED_DIR = os.path.join("data", "sample-feed")


def make_executor(mechanism: str, client):
    if mechanism == "fc":
        return ReActExecutor(client)
    if mechanism == "codegen":
        return CodeGenExecutor(client)
    raise ValueError(f"unknown mechanism {mechanism!r}")


def run_and_grade(scenario, executor, mechanism, validator, save_dir=None):
    original = Feed.load(FEED_DIR)       # pristine, for grading
    edit_feed = Feed.load(FEED_DIR)      # mutated in place by the run
    result = executor.run(edit_feed, scenario.request)
    if save_dir:
        edit_feed.save(save_dir)
        program = getattr(result, "program", "")
        if program:
            with open(os.path.join(save_dir, "_program.py"), "w", encoding="utf-8") as fh:
                fh.write(program)
    cost = {"mechanism": mechanism, "calls": result.num_calls,
            "repairs": result.repair_rounds_used, "structural_success": result.success}
    return grade(scenario, original, edit_feed, cost, validator=validator)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario", help="scenario id or 'all'")
    ap.add_argument("--mechanism", choices=["fc", "codegen"], default="fc")
    ap.add_argument("--official", action="store_true",
                    help="use the official GTFS validator for the validity dimension")
    args = ap.parse_args()

    ids = list(SCENARIOS) if args.scenario == "all" else [args.scenario.upper()]
    for sid in ids:
        if sid not in SCENARIOS:
            print(f"unknown scenario {sid}; known: {list(SCENARIOS)}", file=sys.stderr)
            return 1

    load_dotenv(override=True)
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        print("ERROR: set OPENAI_API_KEY in .env", file=sys.stderr)
        return 1
    client = OpenAIClient(model=os.getenv("OPENAI_MODEL", "gpt-5.5"), api_key=key,
                          base_url=os.getenv("OPENAI_BASE_URL"))

    validator = validate_feed
    if args.official:
        from gtfs_tools.gtfs_validator import OfficialValidator
        jar = os.getenv("GTFS_VALIDATOR_JAR", os.path.join("vendor", "gtfs-validator-cli.jar"))
        print("setting official-validator baseline ...", file=sys.stderr)
        validator = OfficialValidator(jar).set_baseline(Feed.load(FEED_DIR)).validate

    executor = make_executor(args.mechanism, client)
    reports = []
    for sid in ids:
        print(f"running {sid} [{args.mechanism}] ...", file=sys.stderr)
        save_dir = os.path.join("out", args.mechanism, sid.lower())
        report = run_and_grade(SCENARIOS[sid], executor, args.mechanism, validator, save_dir)
        reports.append(report)
        print(report.render())
        print()

    n_pass = sum(r.overall_pass for r in reports)
    print(f"=== [{args.mechanism}] {n_pass}/{len(reports)} scenarios pass overall ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
