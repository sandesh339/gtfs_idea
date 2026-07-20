"""Read-only query path — answers QUESTIONS about a feed (no edits).

The router sends read-only requests ("list the stops on route X", "how many
trips on Y", "what's the headway of Z") here. A ReAct loop over the READ tools
(plus list_route_stops) gathers what it needs and replies in plain English.
Nothing is mutated, so this never touches the edit/commit/diff machinery.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, List

from .feed import Feed
from .tools import GTFSToolkit, TOOL_SCHEMAS
from .llm import LLMClient

_READ_NAMES = {"find_stop", "find_route", "find_trip", "find_agency",
               "list_trips", "get_stop_times"}

_LIST_ROUTE_STOPS = {
    "name": "list_route_stops",
    "description": "List the ordered stops (with names) of a route by route_id, "
                   "optionally for one direction. Use this to answer 'what stops does route X serve'.",
    "parameters": {"type": "object", "properties": {
        "route_id": {"type": "string"},
        "direction_id": {"type": "string", "description": "0 or 1 (optional)"}},
        "required": ["route_id"]},
}

QUERY_TOOL_SCHEMAS: List[Dict] = [t for t in TOOL_SCHEMAS if t["name"] in _READ_NAMES] + [_LIST_ROUTE_STOPS]
_QUERY_NAMES = _READ_NAMES | {"list_route_stops"}

SYSTEM_PROMPT = """You answer questions about a loaded GTFS transit feed using the read-only tools.

- NEVER modify the feed. Only look things up.
- Resolve names by substring (e.g. a route id may be given directly, or a stop by partial name).
- When you have the answer, reply in clear, concise plain English. For lists, use short bullet or numbered lines.
- If something isn't found, say so plainly.
"""


@dataclass
class QueryResult:
    answer: str
    num_calls: int = 0
    stop_reason: str = ""


class QueryExecutor:
    def __init__(self, client: LLMClient, max_steps: int = 14):
        self.client = client
        self.max_steps = max_steps

    def run(self, feed: Feed, request: str, feed_metadata: str = "") -> QueryResult:
        toolkit = GTFSToolkit(feed)
        user = request if not feed_metadata else f"{request}\n\nFeed: {feed_metadata}"
        messages: List[Dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ]
        calls = 0
        for _ in range(self.max_steps):
            turn = self.client.complete(messages, QUERY_TOOL_SCHEMAS)
            messages.append({"role": "assistant", "content": turn.text,
                             "tool_calls": [{"id": c.id, "name": c.name, "arguments": c.arguments}
                                            for c in turn.tool_calls]})
            if not turn.tool_calls:
                return QueryResult(turn.text or "(no answer produced)", calls, "answered")
            for call in turn.tool_calls:
                obs = self._dispatch(toolkit, call.name, call.arguments)
                calls += 1
                messages.append({"role": "tool", "tool_call_id": call.id, "name": "",
                                 "content": json.dumps(obs)})
        return QueryResult("I couldn't complete the lookup in time — try narrowing the question.",
                           calls, "max_steps")

    @staticmethod
    def _dispatch(toolkit: GTFSToolkit, name: str, args: dict) -> dict:
        if name not in _QUERY_NAMES:
            return {"ok": False, "error": f"unknown or non-read tool {name!r}"}
        try:
            return getattr(toolkit, name)(**args)
        except Exception as e:  # keep the loop alive
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
