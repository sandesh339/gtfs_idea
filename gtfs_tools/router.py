"""The router — the chatbot's intellectual layer.

Looks at a request (plus feed metadata and recent conversation) ONCE and
predicts how to handle it:

  tool_fit   high | medium | low   -> which mechanism fits
  ambiguous  bool                  -> is the request under-specified?
  confidence 0..1
  clarifying_question               -> what to ask, if ambiguous
  reason                            -> short rationale

Dispatch policy (applied by the chat session, PDF §4):
  HIGH   -> function calling
  LOW    -> code generation + repair
  MEDIUM -> try function calling, then fall back to code-gen
  ambiguous -> ask the clarifying question, touch nothing

The same predicted label is what the benchmark later scores against the
human tool-fit labels, so router and app share one classifier.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .feed import Feed
from .llm import LLMClient

ROUTER_SYSTEM = """You are the router for a GTFS transit-feed editing assistant. Classify ONE user request so the system can dispatch it. Do not edit anything.

Decide three things:

1) tool_fit — how well a FIXED library of small, single-purpose editing tools fits:
   - "high": a routine parametric edit that lands on ONE tool call — rename a stop,
     recolor a route, change an agency phone, flag wheelchair access, change one
     headway, move a stop's coordinates.
   - "low": a STRUCTURAL / multi-file cascade — insert or remove a stop mid-route,
     generate reverse-direction trips, split or merge routes/trips, shift a whole
     service, interpolate missing times, renumber sequences. These need open-ended
     logic better written as a program.
   - "medium": in between / genuinely contested.

2) ambiguous — true if the request is missing information needed to act safely:
   which route/trip/stop, which time window, coordinates, the target value, or the
   intended outcome. If true, the system will ASK rather than guess.

3) confidence — your certainty (0..1).

4) is_query — true if the user is ASKING for information about the feed rather than
   requesting a change (e.g. "list the stops on route X", "how many trips", "what is
   the headway", "show me..."). Read-only questions are ANSWERED, not edited. If the
   user wants to modify the feed, is_query is false.

If ambiguous, put the single most useful question in clarifying_question; otherwise
leave it empty. Keep reason to one sentence.

Also produce resolved_request: a SINGLE, self-contained instruction that captures
the user's full intent, folding in any details supplied earlier in the
conversation (e.g. coordinates, a target value, or which route — often given as a
short follow-up answer to a clarifying question). If the latest message is only a
clarification answer, restate the ORIGINAL request with that detail filled in.
If ambiguous, set resolved_request to an empty string."""

ROUTE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "tool_fit": {"type": "string", "enum": ["high", "medium", "low"]},
        "ambiguous": {"type": "boolean"},
        "is_query": {"type": "boolean"},
        "confidence": {"type": "number"},
        "clarifying_question": {"type": "string"},
        "resolved_request": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["tool_fit", "ambiguous", "is_query", "confidence",
                 "clarifying_question", "resolved_request", "reason"],
}


@dataclass
class RouteDecision:
    tool_fit: str
    ambiguous: bool
    confidence: float
    clarifying_question: str
    reason: str
    resolved_request: str = ""
    is_query: bool = False

    @property
    def path(self) -> str:
        if self.is_query:
            return "query"                 # read-only question -> answer, don't edit
        if self.ambiguous:
            return "clarify"
        return {"high": "fc", "low": "codegen", "medium": "fc->codegen"}[self.tool_fit]


def feed_metadata(feed: Feed) -> str:
    routes = ", ".join(r["route_id"] for r in feed.tables.get("routes.txt", []))
    services = ", ".join(sorted({t.get("service_id", "")
                                 for t in feed.tables.get("trips.txt", [])} - {""}))
    return (f"routes: {routes} | services: {services} | "
            f"{len(feed.tables.get('stops.txt', []))} stops | "
            f"{len(feed.tables.get('trips.txt', []))} trips")


class Router:
    def __init__(self, client: LLMClient):
        self.client = client

    def route(self, request: str, feed: Feed,
              history: Optional[List[dict]] = None) -> RouteDecision:
        context = f"Feed: {feed_metadata(feed)}"
        if history:
            recent = "\n".join(f"{h['role']}: {h['text']}" for h in history[-4:])
            context += f"\n\nRecent conversation:\n{recent}"
        messages = [
            {"role": "system", "content": ROUTER_SYSTEM},
            {"role": "user", "content": f"{context}\n\nRequest: {request}"},
        ]
        data = self.client.complete_json(messages, ROUTE_SCHEMA, name="route")
        return RouteDecision(
            tool_fit=data["tool_fit"], ambiguous=bool(data["ambiguous"]),
            confidence=float(data["confidence"]),
            clarifying_question=data.get("clarifying_question", ""),
            reason=data.get("reason", ""),
            resolved_request=data.get("resolved_request", ""),
            is_query=bool(data.get("is_query", False)))
