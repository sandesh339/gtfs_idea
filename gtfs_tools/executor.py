"""ReAct executor for the function-calling path.

Loop: present the frozen tool schemas -> model emits a tool call -> we run it
against the in-memory Feed -> feed the structured observation back -> repeat
until the model calls `finish`. On finish we validate; if it fails and repair
rounds remain, we hand the errors back and let the model keep editing. This is
the mechanism that turns single primitives into a multi-call solution.

Repair budget is counted in ROUNDS (matched to code-gen). Total tool calls and
tokens are recorded as OUTCOMES, not constraints.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from .feed import Feed
from .tools import GTFSToolkit, TOOL_SCHEMAS
from .integrity import validate_feed
from .llm import LLMClient, AssistantTurn

SYSTEM_PROMPT = """You are a GTFS feed editor. You modify a transit feed ONLY by calling the provided tools.

Rules:
- Make exactly the change the user asked for, and nothing else.
- Look things up first (find_*, list_trips, get_stop_times) — never guess an id.
- The tools are deliberately small. Structural edits require composing many calls:
  insert/shift/renumber are separate steps and you must orchestrate them yourself,
  including computing interpolated times.
- When, and only when, the requested change is fully applied, call finish.
- If validation comes back with errors after finish, fix them and call finish again.
"""


@dataclass
class StepRecord:
    name: str
    arguments: dict
    result: dict


@dataclass
class RunResult:
    success: bool
    finished: bool
    steps: List[StepRecord] = field(default_factory=list)
    validation_errors: List[str] = field(default_factory=list)
    repair_rounds_used: int = 0
    stop_reason: str = ""

    @property
    def num_calls(self) -> int:
        return len(self.steps)


class ReActExecutor:
    def __init__(self, client: LLMClient, *, max_steps: int = 50,
                 repair_rounds: int = 3,
                 validator: Callable[[Feed], List[str]] = validate_feed):
        self.client = client
        self.max_steps = max_steps
        self.repair_rounds = repair_rounds
        self.validator = validator

    def run(self, feed: Feed, request: str, feed_metadata: str = "") -> RunResult:
        toolkit = GTFSToolkit(feed)
        dispatch = _build_dispatch(toolkit)
        result = RunResult(success=False, finished=False)

        user = request if not feed_metadata else f"{request}\n\nFeed metadata:\n{feed_metadata}"
        messages: List[Dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ]
        repair_left = self.repair_rounds

        for _ in range(self.max_steps):
            turn: AssistantTurn = self.client.complete(messages, TOOL_SCHEMAS)
            messages.append({
                "role": "assistant", "content": turn.text,
                "tool_calls": [{"id": c.id, "name": c.name, "arguments": c.arguments}
                               for c in turn.tool_calls],
            })

            if not turn.tool_calls:
                result.stop_reason = "model stopped without calling finish"
                return result

            for call in turn.tool_calls:
                if call.name == "finish":
                    errors = self.validator(feed)
                    if not errors:
                        result.steps.append(StepRecord("finish", {}, {"ok": True}))
                        _tool_msg(messages, call.id, {"ok": True, "validation": "clean"})
                        result.success = True
                        result.finished = True
                        result.stop_reason = "finished, validation clean"
                        return result
                    if repair_left <= 0:
                        result.validation_errors = errors
                        result.finished = True
                        result.stop_reason = "repair budget exhausted with errors"
                        _tool_msg(messages, call.id, {"ok": False, "validation_errors": errors})
                        return result
                    repair_left -= 1
                    result.repair_rounds_used += 1
                    _tool_msg(messages, call.id, {
                        "ok": False,
                        "validation_errors": errors,
                        "instruction": "Fix these issues with more tool calls, then call finish again.",
                    })
                    result.steps.append(StepRecord("finish", {}, {"validation_errors": errors}))
                    continue

                obs = dispatch(call.name, call.arguments)
                result.steps.append(StepRecord(call.name, call.arguments, obs))
                _tool_msg(messages, call.id, obs)

        result.stop_reason = f"hit max_steps ({self.max_steps})"
        return result


def _tool_msg(messages: List[Dict], call_id: str, payload: dict) -> None:
    messages.append({"role": "tool", "tool_call_id": call_id,
                     "name": "", "content": json.dumps(payload)})


def _build_dispatch(toolkit: GTFSToolkit) -> Callable[[str, dict], dict]:
    valid = {t["name"] for t in TOOL_SCHEMAS}

    def dispatch(name: str, arguments: dict) -> dict:
        if name not in valid:
            return {"ok": False, "error": f"unknown tool {name!r}"}
        method = getattr(toolkit, name, None)
        if method is None:
            return {"ok": False, "error": f"tool {name!r} not implemented"}
        try:
            return method(**arguments)
        except TypeError as e:
            return {"ok": False, "error": f"bad arguments for {name}: {e}"}
        except Exception as e:  # keep the loop alive; surface as an observation
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    return dispatch
