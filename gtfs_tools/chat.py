"""ChatSession — the stateful proof-of-concept chatbot engine.

Unlike the benchmark (which resets per scenario), the app keeps ONE feed that
evolves across the conversation. Each user message flows through:

  router -> path -> mechanism -> (edit a CLONE) -> commit on success

Editing a clone and committing only on success means a failed or invalid edit
never corrupts the live feed, and every successful edit is undoable.

Dispatch (PDF §4):
  high      -> function calling
  low       -> code generation + repair
  medium    -> try function calling, fall back to code-gen
  ambiguous -> ask the router's clarifying question, change nothing
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .feed import Feed
from .llm import LLMClient
from .router import Router, RouteDecision
from .executor import ReActExecutor
from .codegen import CodeGenExecutor
from .query import QueryExecutor
from .diffing import summarize_changes, entity_changes, structured_diff


@dataclass
class Response:
    kind: str                      # "applied" | "clarify" | "failed" | "codegen_client"
    text: str
    decision: Optional[RouteDecision] = None
    mechanism: str = ""
    changes: List[str] = field(default_factory=list)
    success: bool = False
    cost: dict = field(default_factory=dict)
    program: str = ""              # codegen_client: program for the browser to run
    repair_rounds: int = 0         # codegen_client: repair budget
    diff: Optional[dict] = None    # structured per-change records for the inline changes view


class ChatSession:
    def __init__(self, feed: Feed, client: LLMClient):
        self.feed = feed
        self.original = feed.copy()
        self.client = client
        self.router = Router(client)
        self.fc = ReActExecutor(client)
        self.cg = CodeGenExecutor(client)
        self.query = QueryExecutor(client)
        self.history: List[dict] = []
        self._undo: List[Feed] = []
        self._codegen: Optional[dict] = None   # in-flight client code-gen state

    @classmethod
    def from_state(cls, current: Feed, original: Feed, history: List[dict],
                   client: LLMClient) -> "ChatSession":
        """Rebuild a session from persisted storage (survives Render spin-down).
        Undo is not persisted, so it starts empty."""
        s = cls(current, client)
        s.original = original
        s.history = history or []
        return s

    # ----- main entry -----------------------------------------------------
    def handle(self, message: str, allow_server_codegen: bool = True) -> Response:
        """Route and dispatch. When allow_server_codegen is False, code-gen is
        NOT executed on the server — instead a 'codegen_client' response carries
        a program for the browser (Pyodide) to run, and the client drives the
        loop via codegen_repair / codegen_commit."""
        self.history.append({"role": "user", "text": message})
        decision = self.router.route(message, self.feed, self.history)
        # The router folds multi-turn context (e.g. a clarifying answer) into a
        # self-contained instruction; mechanisms execute THAT, not the raw last
        # message — otherwise "Use 36.9088, -116.7647" loses its intent.
        req = decision.resolved_request.strip() or message

        if decision.path == "query":
            result = self.query.run(self.feed, req)
            resp = Response("answer", result.answer, decision, mechanism="query",
                            cost={"calls": result.num_calls, "repairs": 0})
        elif decision.path == "clarify":
            resp = Response("clarify", decision.clarifying_question or
                            "Could you give more detail?", decision)
        elif decision.path == "fc":
            resp = self._run(self.fc, "function calling", req, decision)
        elif decision.path == "codegen":
            if allow_server_codegen:
                resp = self._run(self.cg, "code generation", req, decision)
            else:
                return self._codegen_client(req, decision)
        else:  # fc -> codegen fallback (medium)
            resp = self._run(self.fc, "function calling", req, decision)
            if not resp.success:
                if allow_server_codegen:
                    resp = self._run(self.cg, "code generation (fallback)", req, decision)
                else:
                    return self._codegen_client(req, decision)

        self.history.append({"role": "assistant", "text": resp.text})
        return resp

    # ----- client (browser/Pyodide) code-gen protocol --------------------
    def _codegen_client(self, message: str, decision: RouteDecision) -> Response:
        """Generate the first program (server-side LLM) but DO NOT execute it —
        hand it to the browser. Conversation state is held server-side."""
        from .codegen import initial_messages
        messages = initial_messages(self.feed, message)
        program = self.cg.generate(messages)
        messages.append({"role": "assistant", "content": f"```python\n{program}\n```"})
        self._codegen = {"messages": messages, "rounds": self.cg.repair_rounds,
                         "calls": 1, "repairs": 0, "decision": decision}
        return Response("codegen_client",
                        "Running a generated program in your browser…", decision,
                        program=program, repair_rounds=self.cg.repair_rounds)

    def codegen_repair(self, error: str):
        """Generate a corrected program from the browser's error. Returns
        (program, rounds_left) or None if the repair budget is exhausted."""
        from .codegen import repair_prompt
        cg = self._codegen
        if not cg or cg["rounds"] <= 0:
            return None
        cg["messages"].append({"role": "user", "content": repair_prompt(error)})
        program = self.cg.generate(cg["messages"])
        cg["messages"].append({"role": "assistant", "content": f"```python\n{program}\n```"})
        cg["rounds"] -= 1
        cg["calls"] += 1
        cg["repairs"] += 1
        return program, cg["rounds"]

    def codegen_commit(self, edited: Feed) -> Response:
        """Validate the browser-produced feed and commit it if clean. On invalid,
        returns a failed Response WITHOUT changing state (client may repair)."""
        decision = self._codegen["decision"] if self._codegen else None
        verrors = self.cg.validator(edited)
        if verrors:
            return Response("failed", "Validation errors:\n" + "\n".join(verrors),
                            decision, success=False)
        changes = summarize_changes(self.feed, edited)
        if not changes:
            return Response("failed", "The program ran but changed nothing.",
                            decision, success=False)
        diff = structured_diff(self.feed, edited)
        cost = {"calls": self._codegen["calls"], "repairs": self._codegen["repairs"]} \
            if self._codegen else {}
        self._undo.append(self.feed)
        self.feed = edited
        self._codegen = None
        resp = Response("applied", "Done via code generation (in your browser).",
                        decision, mechanism="code generation (browser)",
                        changes=changes, success=True, cost=cost, diff=diff)
        self.history.append({"role": "assistant", "text": resp.text})
        return resp

    def _run(self, executor, label: str, message: str, decision: RouteDecision) -> Response:
        clone = self.feed.copy()
        result = executor.run(clone, message)
        cost = {"calls": result.num_calls, "repairs": result.repair_rounds_used}
        if not result.success:
            return Response("failed",
                            f"The {label} path couldn't complete this cleanly "
                            f"({result.stop_reason}).", decision, mechanism=label,
                            success=False, cost=cost)
        changes = summarize_changes(self.feed, clone)
        if not changes:
            return Response("failed",
                            f"The {label} path ran but changed nothing — the request "
                            f"may not have matched anything.", decision,
                            mechanism=label, success=False, cost=cost)
        diff = structured_diff(self.feed, clone)
        self._undo.append(self.feed)
        self.feed = clone
        return Response("applied", f"Done via {label}.", decision,
                        mechanism=label, changes=changes, success=True, cost=cost, diff=diff)

    # ----- session commands ----------------------------------------------
    def undo(self) -> bool:
        if not self._undo:
            return False
        self.feed = self._undo.pop()
        return True

    def reset(self) -> None:
        self.feed = self.original.copy()
        self._undo.clear()

    def save(self, out_dir: str) -> None:
        self.feed.save(out_dir)

    def pending_changes(self) -> List[str]:
        """All changes vs the originally loaded feed."""
        return summarize_changes(self.original, self.feed)

    def feed_summary(self) -> str:
        from .router import feed_metadata
        return feed_metadata(self.feed)
