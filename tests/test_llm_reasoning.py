"""Reasoning-effort control on the LLM client.

qwen3.8 emits ~1.7s of hidden thinking before its first spoken word, which is
what keeps the spec SS9 gate at 2.59s (docs/latency.md). Ollama's native
`think` parameter is silently DROPPED by its OpenAI-compatible endpoint, and
Qwen's `/no_think` prompt switch only gets partway. `reasoning_effort` is the
OpenAI-standard control and Ollama honours it: measured 0.19s to first content
versus 1.43s baseline.

It must be opt-in and must not appear in the request at all when unset, so
endpoints that reject unknown parameters keep working.
"""
from types import SimpleNamespace

from assistant.config import Config, load_config
from assistant.llm.client import LLMClient


class RecordingClient:
    def __init__(self):
        self.kwargs = None
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.kwargs = kwargs
        message = SimpleNamespace(content="hi", tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class RecordingStreamClient(RecordingClient):
    def _create(self, **kwargs):
        self.kwargs = kwargs
        delta = SimpleNamespace(content="hi", tool_calls=None)
        return iter([SimpleNamespace(choices=[SimpleNamespace(delta=delta)])])


def test_reasoning_effort_defaults_to_unset():
    """Absent config must leave the request byte-identical to before."""
    fake = RecordingClient()
    LLMClient(Config(), client=fake).chat([], [])
    assert "extra_body" not in fake.kwargs or not fake.kwargs.get("extra_body")


def test_reasoning_effort_is_forwarded_when_configured():
    fake = RecordingClient()
    LLMClient(Config(llm_reasoning_effort="none"), client=fake).chat([], [])
    assert fake.kwargs["extra_body"] == {"reasoning_effort": "none"}


def test_reasoning_effort_is_forwarded_on_the_streaming_path_too():
    """The voice path is the one that needs it most; it must not be missed."""
    fake = RecordingStreamClient()
    client = LLMClient(Config(llm_reasoning_effort="none"), client=fake)
    client.chat_stream([], [], on_delta=lambda d: None)
    assert fake.kwargs["extra_body"] == {"reasoning_effort": "none"}
    assert fake.kwargs["stream"] is True


def test_config_exposes_reasoning_effort_default():
    assert load_config(None).llm_reasoning_effort == ""


def test_reasoning_effort_is_loadable_from_yaml(tmp_path):
    f = tmp_path / "config.yaml"
    f.write_text("llm_reasoning_effort: none\n")
    assert load_config(f).llm_reasoning_effort == "none"
