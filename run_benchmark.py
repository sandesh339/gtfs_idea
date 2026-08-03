"""Benchmark runner — sweep models x mechanisms x scenarios x feeds x trials and
write one JSON line per run to results.jsonl.

Stage-1 scoring (no per-scenario correctness oracle): a run PASSES if the
mechanism finished, changed the feed, and introduced no official-validator
errors (baseline-delta). Correctness/damage oracles can be layered on later.

Usage:
  python run_benchmark.py --models mini=gpt-5-mini,std=gpt-5,pro=gpt-5-pro --trials 3
  python run_benchmark.py --limit 2 --trials 1            # tiny smoke run
  python run_benchmark.py --scenarios A1,D1               # subset

Reads OPENAI_API_KEY / OPENAI_BASE_URL from .env.
"""
import argparse
import json
import os
import time

from dotenv import load_dotenv

from gtfs_tools import Feed
from gtfs_tools.executor import ReActExecutor
from gtfs_tools.codegen import CodeGenExecutor
from gtfs_tools.llm import OpenAIClient
from gtfs_tools.diffing import summarize_changes
from gtfs_tools.validation_summary import ValidatorSummarizer
from benchmark_scenarios import SCENARIOS_BY_FEED, SCENARIOS

# tier -> model id (override with --models); set these to ids your key can call.
# GPT-5 family, low->high by size: nano < mini < gpt-5. All run on Chat Completions.
DEFAULT_MODELS = {"nano": "gpt-5-nano", "mini": "gpt-5-mini", "gpt5": "gpt-5"}
FEEDS = {"demo": os.path.join("data", "sample-feed"),
         "mbta": os.path.join("data", "mbta10")}
MECHANISMS = ("fc", "codegen")

# feeds are parsed once and cloned per run (MBTA slice is ~350k stop_times rows).
_FEED_CACHE = {}


def get_pristine(feed_dir):
    if feed_dir not in _FEED_CACHE:
        _FEED_CACHE[feed_dir] = Feed.load(feed_dir)
    return _FEED_CACHE[feed_dir]


def make_executor(mechanism, client):
    return ReActExecutor(client) if mechanism == "fc" else CodeGenExecutor(client)


def done_keys(path):
    keys = set()
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                    keys.add((r["model"], r["mechanism"], r["feed"], r["scenario"], r["trial"]))
                except Exception:
                    pass
    return keys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="", help="tier=modelid,comma-separated (overrides defaults)")
    ap.add_argument("--feeds", default="demo", help="comma-separated feed names from FEEDS")
    ap.add_argument("--mechanisms", default="fc,codegen")
    ap.add_argument("--scenarios", default="", help="comma-separated scenario ids (default: all)")
    ap.add_argument("--trials", type=int, default=3)
    ap.add_argument("--out", default="results.jsonl")
    ap.add_argument("--limit", type=int, default=0, help="cap total runs (smoke)")
    ap.add_argument("--resume", action="store_true", help="skip runs already in --out")
    args = ap.parse_args()

    load_dotenv(override=True)
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        print("ERROR: set OPENAI_API_KEY in .env"); return 1
    base_url = os.getenv("OPENAI_BASE_URL")

    models = dict(DEFAULT_MODELS)
    if args.models:
        models = dict(p.split("=", 1) for p in args.models.split(","))
    feeds = {f: FEEDS[f] for f in args.feeds.split(",") if f in FEEDS}
    mechs = [m for m in args.mechanisms.split(",") if m in MECHANISMS]
    want = set(args.scenarios.split(",")) if args.scenarios else None

    def scen_for(feed_name):
        s = SCENARIOS_BY_FEED.get(feed_name, SCENARIOS)
        return [x for x in s if x[0] in want] if want else s

    summarizer = ValidatorSummarizer()
    skip = done_keys(args.out) if args.resume else set()

    total = len(models) * len(mechs) * args.trials * sum(len(scen_for(f)) for f in feeds)
    print(f"planning {total} runs -> {args.out}  "
          f"({len(models)} models x {len(mechs)} mech x "
          f"{{{', '.join(f'{f}:{len(scen_for(f))}' for f in feeds)}}} scen/feed x {args.trials} trials)")

    n = 0
    with open(args.out, "a", encoding="utf-8") as out:
        for tier, model_id in models.items():
            for feed_name, feed_dir in feeds.items():
                for (sid, group, hyp, request) in scen_for(feed_name):
                    for mech in mechs:
                        for trial in range(1, args.trials + 1):
                            if args.limit and n >= args.limit:
                                print(f"hit --limit {args.limit}"); return 0
                            k = (model_id, mech, feed_name, sid, trial)
                            if k in skip:
                                continue
                            n += 1
                            row = run_one(model_id, tier, mech, feed_name, feed_dir,
                                          sid, group, hyp, request, trial,
                                          key, base_url, summarizer)
                            out.write(json.dumps(row) + "\n"); out.flush()
                            mark = "PASS" if row["passed"] else ("ERR" if row.get("error") else "fail")
                            print(f"[{n}/{total}] {tier:4s} {mech:7s} {feed_name} {sid:3s} t{trial}: "
                                  f"{mark} valid={row['valid']} changed={row['changed']} calls={row['calls']}")
    print(f"done: wrote/updated {args.out}")
    return 0


def run_one(model_id, tier, mech, feed_name, feed_dir, sid, group, hyp, request,
            trial, key, base_url, summarizer):
    row = {"model": model_id, "tier": tier, "mechanism": mech, "feed": feed_name,
           "scenario": sid, "group": group, "hypothesis": hyp, "trial": trial}
    client = OpenAIClient(model=model_id, api_key=key, base_url=base_url)
    pristine = get_pristine(feed_dir)   # parsed once, treated read-only
    edit = pristine.copy()              # independent clone the executor mutates
    t0 = time.perf_counter()
    try:
        result = make_executor(mech, client).run(edit, request)
        row["success"] = result.success
        row["stop_reason"] = getattr(result, "stop_reason", "")
        row["calls"] = result.num_calls
        row["repairs"] = result.repair_rounds_used
        changed = bool(summarize_changes(pristine, edit))
        row["changed"] = changed
        if changed:
            vs = summarizer.summarize(pristine, edit, feed_name)
            row["valid"] = vs["valid"]
            row["introduced_errors"] = vs["introduced_errors"]
            row["introduced_codes"] = vs["introduced_codes"]
            row["introduced_warnings"] = vs["introduced_warnings"]
        else:
            row["valid"] = True; row["introduced_errors"] = 0
            row["introduced_codes"] = {}; row["introduced_warnings"] = 0
        row["passed"] = bool(result.success and changed and row["valid"])
        row["error"] = None
    except Exception as e:
        row.update(success=False, stop_reason="exception", calls=0, repairs=0,
                   changed=False, valid=None, introduced_errors=None,
                   introduced_codes={}, introduced_warnings=None, passed=False,
                   error=f"{type(e).__name__}: {e}")
    row["tokens"] = getattr(client, "total_tokens", None)
    row["latency_s"] = round(time.perf_counter() - t0, 2)
    return row


if __name__ == "__main__":
    raise SystemExit(main())
