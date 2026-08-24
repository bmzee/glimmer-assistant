from __future__ import annotations

import hashlib
import json

from assistant.agent.compaction import compact, should_compact
from assistant.agent.confirmations import confirmation_for
from assistant.agent.prompts import SYSTEM_PROMPT
from assistant.security.gate import PermissionGate
from assistant.security.log import ActionLog
from assistant.security.quarantine import datamark
from assistant.security.trust import SessionTrust
from assistant.tools.registry import RiskTier, ToolRegistry
# Pure text handling (imports only `re`); no voice dependency is pulled in.
from assistant.voice.streaming import SentenceAccumulator, split_sentences


def _decoded_args(raw: str) -> dict:
    """Arguments for phrasing only. Malformed JSON is _execute's problem to
    report; here it just means there is nothing to build a sentence from."""
    try:
        decoded = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


class AgentLoop:
    def __init__(
        self,
        llm,
        registry: ToolRegistry,
        gate: PermissionGate,
        platform: str,
        max_iterations: int = 15,
        tool_result_max_chars: int = 16000,
        log: ActionLog | None = None,
        trust: SessionTrust | None = None,
        context_max_tokens: int = 131072,
        compact_threshold: float = 0.65,
        min_sentence_chars: int = 0,
    ):
        self._llm = llm
        self._registry = registry
        self._gate = gate
        self._platform = platform
        self._max_iterations = max_iterations
        self._max_chars = tool_result_max_chars
        self._log = log
        self._trust = trust
        self._context_max_tokens = context_max_tokens
        self._compact_threshold = compact_threshold
        self._min_sentence_chars = min_sentence_chars

    def run(self, user_text: str, on_sentence=None) -> str:
        """Run a turn.

        With ``on_sentence`` the loop streams and hands over each sentence the
        moment it completes, so speech starts before generation finishes. Without
        it the blocking API is used and behaviour is unchanged.
        """
        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ]
        schemas = self._registry.schemas(self._platform)

        # Actions already reported to the user straight from their tool result.
        confirmed: list[str] = []
        # Set once anything ran that only the model can put into words: a query,
        # a failure, a denial. From then on its narration is the answer.
        narration_needed = False

        for _ in range(self._max_iterations):
            if should_compact(messages, self._context_max_tokens, self._compact_threshold):
                # Escalate keep_recent only as far as needed to drop below threshold
                for keep in (6, 4, 2):
                    candidate = compact(messages, keep_recent=keep)
                    messages = candidate
                    if not should_compact(candidate, self._context_max_tokens, self._compact_threshold):
                        break
                self._on_compact()

            # After a turn of nothing but successful actions, the model's reply
            # can only restate what the user has already heard, so do not speak
            # it. The call itself still happens: that is where the second tool
            # of a multi-step request comes from.
            redundant = bool(confirmed) and not narration_needed
            msg = self._chat(messages, schemas, None if redundant else on_sentence)
            if not getattr(msg, "tool_calls", None):
                if redundant:
                    return " ".join(confirmed)
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
                result = self._execute(tc.function.name, tc.function.arguments)
                messages.append(
                    {"role": "tool", "tool_call_id": tc.id, "content": result}
                )
                phrase = confirmation_for(
                    tc.function.name, _decoded_args(tc.function.arguments), result
                )
                if phrase is None:
                    narration_needed = True
                    continue
                confirmed.append(phrase)
                if on_sentence is not None:
                    on_sentence(phrase)

        limit = "I hit my step limit before finishing; here is where I stopped."
        if on_sentence is not None:
            for sentence in split_sentences(limit):
                on_sentence(sentence)
        return limit

    def _chat(self, messages: list[dict], schemas: list[dict], on_sentence):
        if on_sentence is None:
            return self._llm.chat(messages, schemas)
        accumulator = SentenceAccumulator(min_chars=self._min_sentence_chars)

        def on_delta(delta: str) -> None:
            for sentence in accumulator.feed(delta):
                on_sentence(sentence)

        msg = self._llm.chat_stream(messages, schemas, on_delta=on_delta)
        # A turn ending in a tool call may carry a spoken preamble; flush it
        # so the user hears the whole thing, not just its complete sentences.
        for sentence in accumulator.flush():
            on_sentence(sentence)
        return msg

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
                result = datamark(self._truncate(result), tool.name)
                if self._trust is not None:
                    self._trust.note_untrusted_ingest(tool.name)
                output = result
            else:
                output = self._truncate(result)
            status = "ok"
        except Exception as e:  # tool bugs must not kill the loop; the model retries
            output = f"ERROR: {e}"
            if tool.risk_tier >= RiskTier.UNDO:
                output += (
                    "\nThis action may have partially completed. Verify the current "
                    "state with a read-only tool before retrying."
                )
            status = "error"
        if self._log is not None:
            self._log.append(
                {
                    "event": "tool_result",
                    "tool": name,
                    "status": status,
                    "result_sha256": hashlib.sha256(output.encode()).hexdigest(),
                }
            )
        return output

    def _truncate(self, s: str) -> str:
        if len(s) <= self._max_chars:
            return s
        return s[: self._max_chars] + "\n[truncated]"

    def _on_compact(self) -> None:
        if self._log is not None:
            self._log.append({"event": "context_compacted"})
