"""Wire-check the ChatSession end to end with a MockClient (no API key).

Drives: router (json) -> FC dispatch -> tool loop -> commit -> diff summary,
plus the ambiguous -> clarify path, plus /undo.
"""
from gtfs_tools import Feed, MockClient
from gtfs_tools.chat import ChatSession
from gtfs_tools.llm import AssistantTurn, ToolCall


def json_script(messages):
    # the router's user message ends with "Request: <text>"
    last = messages[-1]["content"]
    if "wheelchair" in last.lower():
        return {"tool_fit": "high", "ambiguous": False, "confidence": 0.95,
                "clarifying_question": "", "reason": "single flag edit"}
    return {"tool_fit": "high", "ambiguous": True, "confidence": 0.4,
            "clarifying_question": "Which route and time window?", "reason": "under-specified"}


def tool_script(messages):
    turns = sum(1 for m in messages if m["role"] == "assistant")
    plan = [
        ToolCall("c1", "find_stop", {"query": "Bullfrog"}),
        ToolCall("c2", "update_stop", {"stop_id": "BULLFROG", "wheelchair_boarding": "1"}),
        ToolCall("c3", "finish", {}),
    ]
    if turns < len(plan):
        return AssistantTurn(text=None, tool_calls=[plan[turns]])
    return AssistantTurn(text="done", tool_calls=[])


client = MockClient(tool_script, json_script=json_script)
session = ChatSession(Feed.load("data/sample-feed"), client)

print("== ambiguous request ==")
r = session.handle("make the morning buses more often")
print(r.kind, "->", r.text)
assert r.kind == "clarify"

print("\n== high tool-fit request ==")
r = session.handle("mark the Bullfrog stop as wheelchair accessible")
print(r.kind, r.mechanism, r.cost)
for c in r.changes:
    print("   ", c)
assert r.kind == "applied" and r.success

print("\n== undo ==")
print("undone:", session.undo())
print("changes after undo:", session.pending_changes())
assert session.pending_changes() == []
print("\nOK")
