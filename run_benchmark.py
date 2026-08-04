"""Benchmark runner — sweep models x mechanisms x scenarios x feeds x trials and
write one JSON line per run to results.jsonl.

Stage-1 scoring (no per-scenario correctness oracle): a run PASSES if the
mechanism finished, changed the feed, and introduced no official-validator
errors (baseline-delta). EXCEPT Group F (under-specified), scored inversely:
the right behaviour is to make no confident edit, so "refrained" (no change) is
the pass. Degenerate no-op scenarios are excluded per feed via PRECONDITIONS,
and validation uses a date pinned inside each feed's service window (reproducible).
Correctness/damage oracles can be layered on later.

Usage:
  python run_benchmark.py --models mini=gpt-5-mini,std=gpt-5,pro=gpt-5-pro --trials 3
  python run_benchmark.py --limit 2 --trials 1            # tiny smoke run
  python run_benchmark.py --scenarios A1,D1               # subset

Reads OPENAI_API_KEY / OPENAI_BASE_URL from .env.
"""
import argparse
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv

from gtfs_tools import Feed
from gtfs_tools.executor import ReActExecutor
from gtfs_tools.codegen import CodeGenExecutor
from gtfs_tools.llm import OpenAIClient
from gtfs_tools.diffing import summarize_changes
from gtfs_tools.validation_summary import ValidatorSummarizer, representative_date
from benchmark_scenarios import SCENARIOS_BY_FEED, SCENARIOS
from oracle import run_check, CHECKS as ORACLE_CHECKS


# Per-scenario preconditions: a scenario is only meaningful on a feed if this
# holds. If it fails, the task is a degenerate no-op (correct behaviour is "no
# change"), which Stage-1's changed==True rule would wrongly score as a failure,
# so we EXCLUDE it for that feed instead of counting it. Extend as needed.
def _has_blank_times(feed) -> bool:
    return any(r.get("arrival_time", "") == "" or r.get("departure_time", "") == ""
               for r in feed.tables.get("stop_times.txt", []))


PRECONDITIONS = {
    "D2": _has_blank_times,   # "fill blank times" is a no-op if the feed times every stop
}

# Exception types that are transient (worth retrying) vs deterministic (a real,
# repeatable outcome such as a context-window overflow).
_TRANSIENT_ERRORS = {"APIConnectionError", "APITimeoutError", "APIConnectionTimeoutError",
                     "RateLimitError", "InternalServerError", "Timeout", "ConnectionError"}


def classify_error(exc: Exception) -> str:
    name = type(exc).__name__
    if name in _TRANSIENT_ERRORS or "429" in str(exc) or "timeout" in str(exc).lower():
        return "transient"
    return "deterministic"

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
    ap.add_argument("--retry-errors", action="store_true",
                    help="with --resume, drop error rows from --out first so they re-run "
                         "(otherwise a transient failure becomes a permanent gap)")
    ap.add_argument("--workers", type=int, default=1,
                    help="parallel workers (runs are I/O-bound; try 3-4). 1 = sequential")
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

    # --retry-errors: drop error rows from --out so they are re-run (not skipped).
    if args.retry_errors and os.path.exists(args.out):
        kept = [l for l in open(args.out, encoding="utf-8")
                if l.strip() and not json.loads(l).get("error")]
        dropped = sum(1 for _ in open(args.out, encoding="utf-8")) - len(kept)
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.writelines(kept)
        print(f"--retry-errors: dropped {dropped} error rows from {args.out}")

    skip = done_keys(args.out) if args.resume else set()

    # Warm the shared caches ONCE, single-threaded, so the worker pool only ever
    # READS them (no first-touch races): parse each feed, PIN a reproducible
    # validation date inside its service window, and compute the baseline. After
    # this the pristine feed and baseline dicts are read-only; each run clones the
    # feed and only edited feeds hit java (in isolated tmpdirs).
    for feed_name, feed_dir in feeds.items():
        pristine = get_pristine(feed_dir)
        vdate = representative_date(pristine)
        summarizer.set_feed_date(feed_name, vdate)
        summarizer.baseline(pristine, feed_name)
        print(f"  feed {feed_name}: pinned validation date = {vdate}")

    # Exclude degenerate (no-op) scenarios per feed via preconditions (Stage-1:
    # a correct no-op must not be scored as a capability failure).
    excluded = set()
    for feed_name, feed_dir in feeds.items():
        pristine = get_pristine(feed_dir)
        for (sid, group, hyp, request) in scen_for(feed_name):
            pre = PRECONDITIONS.get(sid)
            if pre and not pre(pristine):
                excluded.add((feed_name, sid))
                print(f"  excluding {feed_name}/{sid}: precondition not met (no-op on this feed)")
            elif group != "F" and sid in ORACLE_CHECKS and \
                    run_check(sid, pristine, pristine, False).ok is True:
                excluded.add((feed_name, sid))
                print(f"  excluding {feed_name}/{sid}: already satisfied in pristine feed (no-op)")

    # Flatten to an independent task list (skip already-done, honour --limit).
    tasks = []
    for tier, model_id in models.items():
        for feed_name, feed_dir in feeds.items():
            for (sid, group, hyp, request) in scen_for(feed_name):
                if (feed_name, sid) in excluded:
                    continue
                for mech in mechs:
                    for trial in range(1, args.trials + 1):
                        if (model_id, mech, feed_name, sid, trial) in skip:
                            continue
                        tasks.append((model_id, tier, mech, feed_name, feed_dir,
                                      sid, group, hyp, request, trial))
    if args.limit:
        tasks = tasks[:args.limit]
    ntodo = len(tasks)
    print(f"planning {ntodo} runs -> {args.out}  "
          f"({len(models)} models x {len(mechs)} mech x "
          f"{{{', '.join(f'{f}:{len(scen_for(f))}' for f in feeds)}}} scen/feed x "
          f"{args.trials} trials; {len(skip)} skipped; workers={args.workers})")

    lock = threading.Lock()
    counter = {"n": 0}

    def work(spec):
        return run_one(*spec, key, base_url, summarizer)

    with open(args.out, "a", encoding="utf-8") as out:
        def record(row):
            with lock:
                counter["n"] += 1
                out.write(json.dumps(row) + "\n"); out.flush()
                mark = "PASS" if row["passed"] else ("ERR" if row.get("error") else "fail")
                print(f"[{counter['n']}/{ntodo}] {row['tier']:4s} {row['mechanism']:7s} "
                      f"{row['feed']} {row['scenario']:3s} t{row['trial']}: {mark} "
                      f"valid={row['valid']} changed={row['changed']} calls={row['calls']} "
                      f"lat={row['latency_s']}s")

        if args.workers <= 1:
            for spec in tasks:
                record(work(spec))
        else:
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                for fut in as_completed([pool.submit(work, spec) for spec in tasks]):
                    record(fut.result())
    print(f"done: wrote/updated {args.out}")
    return 0


def run_one(model_id, tier, mech, feed_name, feed_dir, sid, group, hyp, request,
            trial, key, base_url, summarizer):
    row = {"model": model_id, "tier": tier, "mechanism": mech, "feed": feed_name,
           "scenario": sid, "group": group, "hypothesis": hyp, "trial": trial}
    client = None
    t0 = time.perf_counter()
    try:
        client = OpenAIClient(model=model_id, api_key=key, base_url=base_url)
        pristine = get_pristine(feed_dir)   # parsed once, treated read-only
        edit = pristine.copy()              # independent clone the executor mutates
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
        # Group F (under-specified) is scored INVERSELY: the correct behaviour is
        # to make no confident edit, so "refrained" (no change, no error) = pass.
        # All other groups: a valid change that the mechanism completed = pass.
        # Stage-1 outcome taxonomy (passed <=> outcome in {pass, refrained}):
        #   no_change  - mechanism made no edit (stalled / gave up)
        #   invalid    - changed the feed but introduced validator errors
        #   incomplete - a valid change, but the agent never finished (e.g. hit
        #                the call ceiling): a partial edit, not a clean pass
        #   pass       - a valid change that the agent completed
        # Group F is inverted: refraining from a vague request is the pass.
        if group == "F":
            row["passed"] = not changed
            row["outcome"] = "refrained" if not changed else "acted"
        else:
            if not changed:
                row["outcome"] = "no_change"
            elif not row["valid"]:
                row["outcome"] = "invalid"
            elif not result.success:
                row["outcome"] = "incomplete"
            else:
                row["outcome"] = "pass"
            row["passed"] = row["outcome"] == "pass"
        # Stage-2 correctness oracle: did the INTENDED edit actually happen?
        chk = run_check(sid, pristine, edit, changed)
        row["correct"] = chk.ok                       # True / False / None (no oracle)
        row["correct_reason"] = (chk.reason or "")[:120]
        row["passed2"] = bool(row["passed"] and chk.ok)   # completed a CORRECT valid change
        row["ceiling"] = "max_steps" in (row["stop_reason"] or "")
        row["error"] = None
        row["error_kind"] = None
    except Exception as e:
        row.update(success=False, stop_reason="exception", calls=0, repairs=0,
                   changed=False, valid=None, introduced_errors=None,
                   introduced_codes={}, introduced_warnings=None, passed=False,
                   ceiling=False, outcome="error", correct=None,
                   correct_reason="run errored", passed2=False,
                   error=f"{type(e).__name__}: {e}", error_kind=classify_error(e))
    row["tokens"] = getattr(client, "total_tokens", None) if client else None
    row["latency_s"] = round(time.perf_counter() - t0, 2)
    return row


if __name__ == "__main__":
    raise SystemExit(main())
