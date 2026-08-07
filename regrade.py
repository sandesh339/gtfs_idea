"""Re-grade saved runs OFFLINE — no API, no model calls.

Reconstructs each run's edited feed from its persisted delta (runs/…) and re-runs
the correctness oracle. Use this after tweaking an oracle check, adding a new
scenario checker, or (later) adding a damage/scope dimension — none of it costs
API, because the edited feeds were saved at run time by run_benchmark --save-dir.

Runs with no saved feed (produced before persistence, or errored) are left as-is
and counted as 'unsaved'. no-change runs need no artifact (edited == pristine).

Usage:  python regrade.py --in results_mbta.jsonl [--out results_regraded.jsonl]
"""
import argparse
import json
import os

from gtfs_tools import Feed
from gtfs_tools.run_store import load_edit
from oracle import run_check
from run_benchmark import FEEDS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="results_mbta.jsonl")
    ap.add_argument("--out", default="", help="default: overwrite --in")
    args = ap.parse_args()

    rows = [json.loads(l) for l in open(args.inp, encoding="utf-8") if l.strip()]
    cache = {}

    def pristine(feed):
        if feed not in cache:
            cache[feed] = Feed.load(FEEDS[feed])
        return cache[feed]

    regraded = unsaved = errored = flips = 0
    for r in rows:
        if r.get("error"):
            errored += 1
            continue
        pr = pristine(r["feed"])
        if r.get("changed"):
            ep = r.get("edit_path")
            if not (ep and os.path.exists(ep)):
                unsaved += 1
                continue
            edit = load_edit(ep, pr)
        else:
            edit = pr                      # no change -> edited feed == pristine
        chk = run_check(r["scenario"], pr, edit, r.get("changed"))
        before = r.get("correct")
        r["correct"] = chk.ok
        r["correct_reason"] = (chk.reason or "")[:120]
        r["passed2"] = bool(r.get("passed") and chk.ok)
        flips += (before != chk.ok)
        regraded += 1

    out = args.out or args.inp
    with open(out, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    print(f"re-graded {regraded} runs OFFLINE (no API) | {flips} verdict changes | "
          f"{unsaved} changed runs had no saved feed | {errored} errored (skipped) -> {out}")


if __name__ == "__main__":
    main()
