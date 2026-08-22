from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from openai import OpenAI

from assistant.config import Config


@dataclass
class _StreamedFunction:
    name: str = ""
    arguments: str = ""


@dataclass
class _StreamedToolCall:
    id: str = ""
    function: _StreamedFunction = field(default_factory=_StreamedFunction)
    type: str = "function"


@dataclass
class _StreamedReply:
    """Mirrors the shape of a non-streaming chat message.

    The agent loop reads ``.content`` and ``.tool_calls`` off whatever chat()
    returns; assembling the stream into the same shape keeps the loop's tool
    handling identical between the streaming and non-streaming paths.
    """

    content: str = ""
    tool_calls: list = field(default_factory=list)


class LLMClient:
    def __init__(self, cfg: Config, client=None):
        self._client = (
            client if client is not None else OpenAI(base_url=cfg.llm_base_url, api_key=cfg.llm_api_key)
        )
        self._model = cfg.llm_model
        self._timeout = cfg.llm_timeout_seconds

    def chat(self, messages: list[dict], tools: list[dict]):
        response = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            tools=tools or None,
            timeout=self._timeout,
        )
        return response.choices[0].message

    def chat_stream(
        self,
        messages: list[dict],
        tools: list[dict],
        on_delta: Callable[[str], None],
    ) -> _StreamedReply:
        """Stream a turn, reporting text deltas as they arrive.

        ``on_delta`` fires only for prose, never for tool-call fragments, so a
        caller can pipe it straight to TTS without speaking a half-formed tool
        call. Returns the fully assembled reply once the stream ends.
        """
        stream = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            tools=tools or None,
            timeout=self._timeout,
            stream=True,
        )
        reply = _StreamedReply()
        by_index: dict[int, _StreamedToolCall] = {}

        for chunk in stream:
            choices = getattr(chunk, "choices", None)
            if not choices:
                continue  # keepalive / usage-only chunks carry no delta
            delta = getattr(choices[0], "delta", None)
            if delta is None:
                continue

            text = getattr(delta, "content", None)
            if text:
                reply.content += text
                on_delta(text)

            for fragment in getattr(delta, "tool_calls", None) or []:
                index = getattr(fragment, "index", 0) or 0
                call = by_index.setdefault(index, _StreamedToolCall())
                if getattr(fragment, "id", None):
                    call.id = fragment.id
                function = getattr(fragment, "function", None)
                if function is not None:
                    if getattr(function, "name", None):
                        call.function.name = function.name
                    if getattr(function, "arguments", None):
                        call.function.arguments += function.arguments

        reply.tool_calls = [by_index[i] for i in sorted(by_index)]
        return reply
