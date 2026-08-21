from types import SimpleNamespace

from assistant.config import Config
from assistant.llm.client import LLMClient


class StubCompletions:
    def __init__(self, message):
        self._message = message
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return SimpleNamespace(choices=[SimpleNamespace(message=self._message)])


def make_stub(message):
    completions = StubCompletions(message)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return client, completions


def test_chat_returns_message_and_passes_args():
    msg = SimpleNamespace(content="hi", tool_calls=None)
    stub, completions = make_stub(msg)
    llm = LLMClient(Config(llm_model="m1"), client=stub)

    tools = [{"type": "function", "function": {"name": "t", "parameters": {}}}]
    out = llm.chat([{"role": "user", "content": "x"}], tools)

    assert out is msg
    assert completions.last_kwargs["model"] == "m1"
    assert completions.last_kwargs["messages"] == [{"role": "user", "content": "x"}]
    assert completions.last_kwargs["tools"] == tools


def test_empty_tools_sent_as_none():
    stub, completions = make_stub(SimpleNamespace(content="hi", tool_calls=None))
    llm = LLMClient(Config(), client=stub)
    llm.chat([{"role": "user", "content": "x"}], [])
    assert completions.last_kwargs["tools"] is None
