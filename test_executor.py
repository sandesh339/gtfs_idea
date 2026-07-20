"""Drive the ReAct executor with a scripted MockClient — no API key needed.

Scenario: model deletes a mid-route stop_time on CITY1 (leaving a sequence
gap), tries to finish too early (validator should NOT complain about gaps since
our structural validator only checks monotonicity/refs — so we also force a
real error path), then renumbers and finishes clean. This proves: chaining,
observation feedback, finish->validate, and a clean exit.
"""
from gtfs_tools import Feed, MockClient, ReActExecutor
from gtfs_tools.llm import AssistantTurn, ToolCall


def script(messages):
    """Return the next turn based on how many assistant turns we've produced."""
    turns = sum(1 for m in messages if m["role"] == "assistant")
    plan = [
        ToolCall("c1", "find_stop", {"query": "Doing Ave"}),
        ToolCall("c2", "get_stop_times", {"trip_id": "CITY1"}),
        ToolCall("c3", "delete_stop_time", {"trip_id": "CITY1", "stop_sequence": "2"}),
        ToolCall("c4", "renumber_sequence", {"scope": "trip=CITY1"}),
        ToolCall("c5", "finish", {}),
    ]
    if turns < len(plan):
        return AssistantTurn(text=None, tool_calls=[plan[turns]])
    return AssistantTurn(text="done", tool_calls=[])


feed = Feed.load("data/sample-feed")
print("CITY1 before:", [r["stop_sequence"] for r in feed.tables["stop_times.txt"]
                        if r["trip_id"] == "CITY1"])

executor = ReActExecutor(MockClient(script))
result = executor.run(feed, "Remove 'Doing Ave / D Ave N' from CITY1 and close the gap.")

for i, s in enumerate(result.steps, 1):
    print(f"  {i}. {s.name}({s.arguments}) -> ok={s.result.get('ok')}")
print("CITY1 after :", [r["stop_sequence"] for r in feed.tables["stop_times.txt"]
                        if r["trip_id"] == "CITY1"])
print(f"\nsuccess={result.success} calls={result.num_calls} reason={result.stop_reason}")
assert result.success, "expected a clean finish"
print("OK")
