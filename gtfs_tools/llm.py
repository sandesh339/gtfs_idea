"""Provider-agnostic LLM client.

The executor speaks ONE neutral message/tool format; each provider client
translates to and from its own API. Adding Gemini/Qwen/DeepSeek later means
writing one more subclass — the executor never changes.

Neutral message shapes (list of dicts):
  {"role": "system", "content": str}
  {"role": "user",   "content": str}
  {"role": "assistant", "content": str|None,
       "tool_calls": [{"id": str, "name": str, "arguments": dict}]}
  {"role": "tool", "tool_call_id": str, "name": str, "content": str}
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class AssistantTurn:
    text: Optional[str]
    tool_calls: List[ToolCall] = field(default_factory=list)


class LLMClient(ABC):
    name: str = "abstract"

    @abstractmethod
    def complete(self, messages: List[Dict], tools: List[Dict]) -> AssistantTurn:
        """One model turn given neutral messages + neutral tool schemas."""
        raise NotImplementedError

    @abstractmethod
    def complete_json(self, messages: List[Dict], schema: Dict, name: str = "response") -> dict:
        """One model turn constrained to a JSON schema (used by the router)."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
class OpenAIClient(LLMClient):
    """GPT family via the OpenAI chat-completions API."""

    def __init__(self, model: str, api_key: str, base_url: Optional[str] = None):
        from openai import OpenAI
        self.model = model
        self.name = f"openai:{model}"
        self._client = OpenAI(api_key=api_key, base_url=base_url or None)

    @staticmethod
    def _tools_to_openai(tools: List[Dict]) -> List[Dict]:
        return [{"type": "function", "function": t} for t in tools]

    @staticmethod
    def _messages_to_openai(messages: List[Dict]) -> List[Dict]:
        out = []
        for m in messages:
            if m["role"] == "assistant" and m.get("tool_calls"):
                out.append({
                    "role": "assistant",
                    "content": m.get("content") or None,
                    "tool_calls": [
                        {"id": tc["id"], "type": "function",
                         "function": {"name": tc["name"],
                                      "arguments": json.dumps(tc["arguments"])}}
                        for tc in m["tool_calls"]
                    ],
                })
            elif m["role"] == "tool":
                out.append({"role": "tool", "tool_call_id": m["tool_call_id"],
                            "content": m["content"]})
            else:
                out.append({"role": m["role"], "content": m.get("content", "")})
        return out

    def complete(self, messages: List[Dict], tools: List[Dict]) -> AssistantTurn:
        kwargs = {"model": self.model, "messages": self._messages_to_openai(messages)}
        if tools:  # code-gen path calls with no tools -> plain completion
            kwargs["tools"] = self._tools_to_openai(tools)
            kwargs["tool_choice"] = "auto"
        resp = self._client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message
        calls = []
        for tc in (msg.tool_calls or []):
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"__raw__": tc.function.arguments}
            calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))
        return AssistantTurn(text=msg.content, tool_calls=calls)

    def complete_json(self, messages: List[Dict], schema: Dict, name: str = "response") -> dict:
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=self._messages_to_openai(messages),
            response_format={"type": "json_schema",
                             "json_schema": {"name": name, "schema": schema, "strict": True}},
        )
        return json.loads(resp.choices[0].message.content)


# ---------------------------------------------------------------------------
class MockClient(LLMClient):
    """Deterministic client for testing the loop without an API key.

    `script` is a callable taking the message list and returning an
    AssistantTurn — lets a test drive an exact sequence of tool calls.
    """

    def __init__(self, script: Callable[[List[Dict]], AssistantTurn],
                 json_script: Callable[[List[Dict]], dict] = None):
        self.name = "mock"
        self._script = script
        self._json_script = json_script
        self.turn = 0

    def complete(self, messages: List[Dict], tools: List[Dict]) -> AssistantTurn:
        turn = self._script(messages)
        self.turn += 1
        return turn

    def complete_json(self, messages: List[Dict], schema: Dict, name: str = "response") -> dict:
        if self._json_script is None:
            raise NotImplementedError("MockClient has no json_script")
        return self._json_script(messages)
