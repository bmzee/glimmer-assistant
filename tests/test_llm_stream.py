"""LLMClient.chat_stream: surface content deltas without losing tool calls.

The agent loop cannot simply switch to streaming and drop tool support -- a
turn may come back as prose (speak it) or as tool calls (execute them), and
which one it is only becomes known as the chunks arrive. chat_stream therefore
reports deltas through a callback while assembling a reply object with the same
shape chat() returns, so the loop's tool handling is unchanged.
"""
from types import SimpleNamespace

from assistant.config import Config
from assistant.llm.client import LLMClient


def _chunk(content=None, tool_calls=None):
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


def _tc_delta(index, tc_id=None, name=None, arguments=None):
    return SimpleNamespace(
        index=index,
        id=tc_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


class FakeStreamingClient:
    def __init__(self, chunks):
        self._chunks = chunks
        self.kwargs = None
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.kwargs = kwargs
        return iter(self._chunks)


def _client(chunks):
    fake = FakeStreamingClient(chunks)
    return LLMClient(Config(), client=fake), fake


def test_content_deltas_are_reported_in_order_and_joined():
    client, _ = _client([_chunk("Hello"), _chunk(" there"), _chunk(".")])
    seen = []
    reply = client.chat_stream([], [], on_delta=seen.append)

    assert seen == ["Hello", " there", "."]
    assert reply.content == "Hello there."
    assert not reply.tool_calls


def test_requests_a_stream_from_the_endpoint():
    client, fake = _client([_chunk("hi")])
    client.chat_stream([{"role": "user", "content": "x"}], [], on_delta=lambda d: None)
    assert fake.kwargs["stream"] is True


def test_tool_call_fragments_are_assembled_across_chunks():
    """Arguments arrive split across chunks and must be concatenated."""
    client, _ = _client([
        _chunk(tool_calls=[_tc_delta(0, "call_1", "read_file", '{"pa')]),
        _chunk(tool_calls=[_tc_delta(0, None, None, 'th": "a.txt"}')]),
    ])
    reply = client.chat_stream([], [], on_delta=lambda d: None)

    assert len(reply.tool_calls) == 1
    tc = reply.tool_calls[0]
    assert tc.id == "call_1"
    assert tc.function.name == "read_file"
    assert tc.function.arguments == '{"path": "a.txt"}'


def test_parallel_tool_calls_are_kept_separate_by_index():
    client, _ = _client([
        _chunk(tool_calls=[_tc_delta(0, "a", "open_app", "{}")]),
        _chunk(tool_calls=[_tc_delta(1, "b", "list_dir", "{}")]),
    ])
    reply = client.chat_stream([], [], on_delta=lambda d: None)

    assert [tc.id for tc in reply.tool_calls] == ["a", "b"]
    assert [tc.function.name for tc in reply.tool_calls] == ["open_app", "list_dir"]


def test_tool_call_chunks_emit_no_speech_deltas():
    """Nothing should be spoken while the model is emitting a tool call."""
    client, _ = _client([_chunk(tool_calls=[_tc_delta(0, "a", "open_app", "{}")])])
    seen = []
    client.chat_stream([], [], on_delta=seen.append)
    assert seen == []


def test_tolerates_chunks_with_no_choices():
    """Some endpoints emit keepalive/usage chunks carrying no choices."""
    client, _ = _client([SimpleNamespace(choices=[]), _chunk("ok.")])
    reply = client.chat_stream([], [], on_delta=lambda d: None)
    assert reply.content == "ok."
