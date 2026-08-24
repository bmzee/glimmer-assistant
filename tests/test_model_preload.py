"""Ollama unloads an idle model; reloading 17-25GB costs 16-29s (measured).

That reload lands on the FIRST command after the app opens -- the one that
decides whether the user thinks it works. So load the weights at startup,
before anyone speaks.

The obvious fix does not work: keep_alive sent through Ollama's OpenAI-compat
shim as extra_body is silently DROPPED. Measured against a live server --
plain call 30.0 min, extra_body={'keep_alive': '45m'} 30.0 min (unchanged),
native /api/chat with keep_alive 45.0 min. So the pin has to use the native
endpoint, which is why this is not a one-line change to LLMClient.
"""
import pytest

from assistant.llm.preload import native_chat_url, preload_model


def test_pins_via_the_native_endpoint_because_the_openai_shim_drops_keep_alive():
    sent = []
    preload_model("http://localhost:11434/v1", "m", keep_alive="30m", post=lambda u, b: sent.append((u, b)))

    url, body = sent[0]
    assert url == "http://localhost:11434/api/chat"
    assert "/v1" not in url, "the /v1 shim is exactly what drops keep_alive"
    assert body["keep_alive"] == "30m"
    assert body["model"] == "m"


def test_sends_no_messages_so_the_preload_costs_no_generation():
    """Ollama loads the weights and returns; asking it to answer would burn
    seconds and GPU for output nobody reads."""
    sent = []
    preload_model("http://localhost:11434/v1", "m", post=lambda u, b: sent.append((u, b)))

    assert sent[0][1]["messages"] == []


@pytest.mark.parametrize(
    "base",
    [
        "http://localhost:11434/v1",
        "http://localhost:11434/v1/",
        "http://localhost:11434",
        "http://127.0.0.1:11434/v1",
    ],
)
def test_derives_the_native_url_from_any_reasonable_base(base):
    assert native_chat_url(base).endswith("/api/chat")
    assert "/v1" not in native_chat_url(base)


def test_a_failed_preload_never_stops_the_app_starting():
    """A cold cache is a slow first turn. A raised exception is no app at all."""
    def boom(url, body):
        raise OSError("connection refused")

    assert preload_model("http://localhost:11434/v1", "m", post=boom) is False


def test_reports_whether_the_model_was_actually_pinned():
    assert preload_model("http://localhost:11434/v1", "m", post=lambda u, b: None) is True
