"""CodeRunner — pluggable execution backend for the code-gen path.

Code GENERATION (the LLM call + prompt) is shared and always server-side.
Code EXECUTION is abstracted here so it can run in different places:

  LocalSubprocessRunner  offline benchmark + local dev (runs on this machine)
  (Pyodide, in-browser)  the ONLINE app runs the generated program in the
                         reviewer's browser via WebAssembly, so untrusted code
                         never touches the server. That runner lives in the
                         frontend; the backend only generates/repairs programs.

Keeping this seam means the benchmark and the app share identical generation
logic and prompts — only where the program runs differs.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from .feed import Feed


@dataclass
class ExecutionResult:
    ok: bool                       # did the program run without crashing?
    feed: Optional[Feed] = None    # the edited feed (present iff ok)
    error: str = ""                # crash/timeout message (present iff not ok)


class CodeRunner(ABC):
    @abstractmethod
    def run(self, program: str, feed: Feed) -> ExecutionResult:
        """Run `program` against a COPY of `feed`; return the edited feed or an
        error. Must not mutate the input feed."""
        raise NotImplementedError


class LocalSubprocessRunner(CodeRunner):
    """Runs the program in a subprocess in an isolated temp dir. Fine for the
    offline benchmark and local dev; NOT a security sandbox — do not use for
    untrusted input on a shared server (see coderunner module docstring)."""

    def __init__(self, timeout: int = 30):
        self.timeout = timeout

    def run(self, program: str, feed: Feed) -> ExecutionResult:
        with tempfile.TemporaryDirectory() as workdir:
            feed.save(workdir)                     # fresh copy of the feed
            prog_path = os.path.join(workdir, "_program.py")
            with open(prog_path, "w", encoding="utf-8") as fh:
                fh.write(program)
            env = {k: v for k, v in os.environ.items()
                   if not k.startswith(("OPENAI", "GEMINI", "DEEPSEEK", "QWEN",
                                        "ANTHROPIC", "SUPABASE", "REVIEWER"))}
            try:
                proc = subprocess.run(
                    [sys.executable, "_program.py"], cwd=workdir, env=env,
                    capture_output=True, text=True, timeout=self.timeout)
            except subprocess.TimeoutExpired:
                return ExecutionResult(ok=False, error=f"timed out after {self.timeout}s")
            if proc.returncode != 0:
                return ExecutionResult(
                    ok=False, error=(proc.stderr or proc.stdout or "non-zero exit").strip())
            # program mutated the .txt files in place; load the result back
            edited = Feed.load(workdir)
            return ExecutionResult(ok=True, feed=edited)
