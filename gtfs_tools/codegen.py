"""Code-generation path — the second execution mechanism.

The model writes ONE Python program that edits the GTFS feed files in place.
We run it in an isolated working directory, validate the result, and on failure
(crash OR validation errors) hand the error back for a corrected program, up to
a repair budget matched to the FC path (repair ROUNDS). Same grader scores the
output, so this is a fair head-to-head with function calling.

The harness is written ONCE and frozen — identical prompt/loop for every
scenario — the code-gen analogue of the frozen tool library (validity rule).

SECURITY NOTE: this executes model-written Python in a subprocess with a fresh
copy of the feed, a timeout, and a scrubbed environment. It is NOT a hard
sandbox. Intended for local benchmark runs with frontier models, not untrusted
input.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .feed import Feed
from .integrity import validate_feed
from .llm import LLMClient
from .coderunner import CodeRunner, LocalSubprocessRunner

SYSTEM_PROMPT = """You edit a GTFS feed by writing ONE complete, self-contained Python program.

Environment:
- The current working directory contains the GTFS feed as CSV files (*.txt).
- Python 3.11 with the standard library and pandas are available.
- GTFS times are HH:MM:SS and MAY exceed 24:00:00 (e.g. 25:30:00). Handle them
  as seconds-since-midnight if you do time math; keep empty times empty.

Task:
- Read the relevant file(s), make EXACTLY the requested change and nothing else,
  and write the file(s) back IN PLACE (same filenames, CSV, keep all columns).
- Do not print anything you don't need. Do not touch unrelated rows or files.

Name resolution:
- Entity names in the request may be PARTIAL and may omit suffixes present in the
  data (e.g. a stop stored as 'Bullfrog (Demo)' can be referred to as 'Bullfrog';
  a route stored with long_name 'City' may be named by short_name '40').
- Resolve names case-insensitively by substring/contains, the way a lookup tool
  would — never by exact string equality. Verify you matched exactly the intended
  row(s); if a filter matches zero rows, your matching is too strict.

Output:
- Reply with ONE ```python code block containing the full program. No prose.
- If told your program failed, reply with a corrected FULL program (not a diff).
"""

_CODE_RE = re.compile(r"```(?:python)?\s*(.*?)```", re.DOTALL)


@dataclass
class CodeGenResult:
    success: bool
    llm_calls: int = 0
    repair_rounds_used: int = 0
    program: str = ""
    error: str = ""
    stop_reason: str = ""
    attempts: List[dict] = field(default_factory=list)

    @property
    def num_calls(self) -> int:      # parity with the FC RunResult field name
        return self.llm_calls


def _extract_code(text: Optional[str]) -> str:
    if not text:
        return ""
    m = _CODE_RE.search(text)
    return (m.group(1) if m else text).strip()


def schema_summary(feed: Feed) -> str:
    lines = []
    for name in sorted(feed.tables):
        cols = ", ".join(feed.headers.get(name, []))
        lines.append(f"  {name} ({len(feed.tables[name])} rows): {cols}")
    return "\n".join(lines)


def initial_messages(feed: Feed, request: str, feed_metadata: str = "") -> List[Dict]:
    """The starting conversation for code generation. Shared by the offline
    executor and the online (Pyodide) backend so both use identical prompts."""
    user = (f"{request}\n\nFeed files and columns:\n{schema_summary(feed)}"
            + (f"\n\n{feed_metadata}" if feed_metadata else ""))
    return [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user}]


def repair_prompt(error: str) -> str:
    return f"{error}\n\nFix it. Reply with the full corrected program."


class CodeGenExecutor:
    def __init__(self, client: LLMClient, *, repair_rounds: int = 3,
                 runner: Optional[CodeRunner] = None, validator=validate_feed):
        self.client = client
        self.repair_rounds = repair_rounds
        self.runner = runner or LocalSubprocessRunner()
        self.validator = validator

    def generate(self, messages: List[Dict]) -> str:
        """One generation turn -> the extracted program (LLM call)."""
        turn = self.client.complete(messages, tools=[])
        return _extract_code(turn.text)

    def run(self, feed: Feed, request: str, feed_metadata: str = "") -> CodeGenResult:
        """Run the code-gen loop via self.runner. On success, `feed` is replaced
        in place with the edited feed (matching the FC executor's API)."""
        result = CodeGenResult(success=False)
        source = feed.copy()      # immutable snapshot; runner gets a fresh copy each attempt
        messages = initial_messages(feed, request, feed_metadata)

        for attempt in range(self.repair_rounds + 1):
            program = self.generate(messages)
            result.llm_calls += 1
            result.program = program

            exec_result = self.runner.run(program, source)
            if not exec_result.ok:
                error = f"Program crashed:\n{exec_result.error}"
            else:
                verrors = self.validator(exec_result.feed)
                error = ("Validation errors:\n" + "\n".join(verrors)) if verrors else ""

            result.attempts.append({"attempt": attempt, "error": error[:500]})

            if not error:
                _replace_feed(feed, exec_result.feed)
                result.success = True
                result.stop_reason = "program ran, validation clean"
                return result

            if attempt == self.repair_rounds:
                result.error = error
                result.stop_reason = "repair budget exhausted"
                return result

            result.repair_rounds_used += 1
            messages.append({"role": "assistant", "content": f"```python\n{program}\n```"})
            messages.append({"role": "user", "content": repair_prompt(error)})

        result.stop_reason = "unexpected"
        return result


def _replace_feed(target: Feed, source: Feed) -> None:
    target.tables = source.tables
    target.headers = source.headers
