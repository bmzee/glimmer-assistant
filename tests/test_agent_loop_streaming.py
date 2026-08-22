"""AgentLoop streaming: hand sentences out mid-generation, not at the end.

The spec SS9 gate measures PTT release -> first TTS audio. Today the loop
returns only when the whole answer exists, so first audio waits on the last
token (docs/latency.md). Passing on_sentence switches the loop to the
streaming client and releases each sentence the moment it completes, which
changes the measured quantity to time-to-first-sentence.

Non-streaming behaviour must be untouched: callers that pass no on_sentence
keep using chat().
"""
import json
from types import SimpleNamespace

from assistant.agent.loop import AgentLoop
from assistant.security.gate import PermissionGate
from assistant.security.log import ActionLog
from assistant.tools.registry import RiskTier, Tool, ToolRegistry


def tool_call(call_id, name, arguments: dict):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
    )


class ScriptedStreamingLLM:
    """Serves scripted turns; records which API the loop actually used.

    Each turn is (list_of_text_deltas, tool_calls_or_None).
    """

    def __init__(self, turns):
        self._turns = list(turns)
        self.chat_calls = 0
        self.stream_calls = 0

    def chat(self, messages, tools):
        self.chat_calls += 1
        deltas, tool_calls = self._turns.pop(0)
        return SimpleNamespace(content="".join(deltas), tool_calls=tool_calls)

    def chat_stream(self, messages, tools, on_delta):
        self.stream_calls += 1
        deltas, tool_calls = self._turns.pop(0)
        for d in deltas:
            on_delta(d)
        return SimpleNamespace(content="".join(deltas), tool_calls=tool_calls)


def make_loop(tmp_path, llm, func=lambda a: "ok", tier=RiskTier.AUTO, **kwargs):
    reg = ToolRegistry()
    reg.register(
        Tool(
            name="echo",
            description="echo",
            parameters={"type": "object", "properties": {}, "required": []},
            risk_tier=tier,
            platforms=("darwin",),
            func=func,
        )
    )
    gate = PermissionGate(ActionLog(tmp_path / "a.jsonl"), confirmer=lambda req: True)
    return AgentLoop(llm, reg, gate, platform="darwin", **kwargs)


def test_without_on_sentence_the_loop_still_uses_the_blocking_api(tmp_path):
    """Text mode must not silently change transport."""
    llm = ScriptedStreamingLLM([(["hello there"], None)])
    loop = make_loop(tmp_path, llm)

    assert loop.run("hi") == "hello there"
    assert llm.chat_calls == 1
    assert llm.stream_calls == 0


def test_with_on_sentence_the_loop_streams(tmp_path):
    llm = ScriptedStreamingLLM([(["hello there."], None)])
    loop = make_loop(tmp_path, llm)

    loop.run("hi", on_sentence=lambda s: None)
    assert llm.stream_calls == 1
    assert llm.chat_calls == 0


def test_sentences_are_released_as_they_complete(tmp_path):
    llm = ScriptedStreamingLLM([(["One.", " Two.", " Three."], None)])
    loop = make_loop(tmp_path, llm)
    spoken = []

    reply = loop.run("hi", on_sentence=spoken.append)

    assert spoken == ["One.", "Two.", "Three."]
    assert reply == "One. Two. Three."


def test_first_sentence_is_released_before_generation_finishes(tmp_path):
    """The entire point: sentence 1 must not wait for the last token.

    Fails on any implementation that buffers the answer and splits at the end.
    """
    order = []

    class SlowTailLLM(ScriptedStreamingLLM):
        def chat_stream(self, messages, tools, on_delta):
            on_delta("Ready.")
            order.append("after-first-delta")
            on_delta(" Still writing the rest.")
            order.append("generation-finished")
            return SimpleNamespace(
                content="Ready. Still writing the rest.", tool_calls=None
            )

    llm = SlowTailLLM([])
    loop = make_loop(tmp_path, llm)
    loop.run("hi", on_sentence=lambda s: order.append(f"spoke:{s}"))

    assert order.index("spoke:Ready.") < order.index("generation-finished")


def test_trailing_text_without_a_terminator_is_still_spoken(tmp_path):
    llm = ScriptedStreamingLLM([(["no terminator"], None)])
    loop = make_loop(tmp_path, llm)
    spoken = []

    reply = loop.run("hi", on_sentence=spoken.append)

    assert spoken == ["no terminator"]
    assert reply == "no terminator"


def test_tool_calls_still_execute_when_streaming(tmp_path):
    calls = []
    llm = ScriptedStreamingLLM([
        ([""], [tool_call("c1", "echo", {})]),
        (["All done."], None),
    ])
    loop = make_loop(tmp_path, llm, func=lambda a: calls.append(a) or "ok")
    spoken = []

    reply = loop.run("hi", on_sentence=spoken.append)

    assert calls == [{}]
    assert reply == "All done."
    assert spoken == ["All done."]


def test_step_limit_message_is_spoken_rather_than_silently_returned(tmp_path):
    """A turn that hits the cap must still produce audio, not silence."""
    llm = ScriptedStreamingLLM([([""], [tool_call("c1", "echo", {})])] * 3)
    loop = make_loop(tmp_path, llm, max_iterations=3)
    spoken = []

    reply = loop.run("hi", on_sentence=spoken.append)

    assert reply
    assert spoken and spoken[0].startswith("I hit my step limit")
