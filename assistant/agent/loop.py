from __future__ import annotations

import json

from assistant.agent.prompts import SYSTEM_PROMPT
from assistant.security.gate import PermissionGate
from assistant.security.quarantine import datamark
from assistant.tools.registry import ToolRegistry


class AgentLoop:
    def __init__(
        self,
        llm,
        registry: ToolRegistry,
        gate: PermissionGate,
        platform: str,
        max_iterations: int = 15,
        tool_result_max_chars: int = 16000,
    ):
        self._llm = llm
        self._registry = registry
        self._gate = gate
        self._platform = platform
        self._max_iterations = max_iterations
        self._max_chars = tool_result_max_chars

    def run(self, user_text: str) -> str:
        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ]
        schemas = self._registry.schemas(self._platform)

        for _ in range(self._max_iterations):
            msg = self._llm.chat(messages, schemas)
            if not getattr(msg, "tool_calls", None):
                return msg.content or ""

            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in msg.tool_calls
                    ],
                }
            )
            for tc in msg.tool_calls:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": self._execute(tc.function.name, tc.function.arguments),
                    }
                )

        return "I hit my step limit before finishing; here is where I stopped."

    def _execute(self, name: str, raw_arguments: str) -> str:
        tool = self._registry.get(name)
        if tool is None or self._platform not in tool.platforms:
            return f"ERROR: unknown tool {name}"
        try:
            args = json.loads(raw_arguments) if raw_arguments else {}
        except json.JSONDecodeError as e:
            return f"ERROR: arguments were not valid JSON: {e}"
        if not self._gate.check(tool, args):
            return "DENIED: the user did not approve this action."
        try:
            result = tool.func(args)
            if tool.untrusted:
                result = datamark(result, tool.name)
            return self._truncate(result)
        except Exception as e:  # tool bugs must not kill the loop; the model retries
            return f"ERROR: {e}"

    def _truncate(self, s: str) -> str:
        if len(s) <= self._max_chars:
            return s
        return s[: self._max_chars] + "\n[truncated]"
