from __future__ import annotations

from openai import OpenAI

from assistant.config import Config


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
