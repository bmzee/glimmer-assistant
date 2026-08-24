"""A second model call to say "Calculator is now open" is pure latency.

Profiled: "open the calculator" is 3.1s deciding + 0.08s ACTUALLY OPENING IT +
1.2s composing a sentence that restates what the tool already reported. The
action is done long before the user hears about it.

So confirm a successful action from the tool result and stop waiting on the
model for it. Two things this must not break:

  - Queries. For read_file/list_dir the model's narration IS the answer; there
    is nothing to template.
  - Multi-step. The loop must still make the follow-up call, because that is
    where a second tool comes from. We suppress the model's PROSE on a
    pure-action turn, never the call itself.
"""
import json
from types import SimpleNamespace

import pytest

from assistant.agent.confirmations import confirmation_for
from assistant.agent.loop import AgentLoop
from assistant.security.gate import PermissionGate
from assistant.security.log import ActionLog
from assistant.tools.registry import RiskTier, Tool, ToolRegistry


def tool_call(call_id, name, arguments: dict):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
    )


class ScriptedLLM:
    """Each turn is (list_of_text_deltas, tool_calls_or_None)."""

    def __init__(self, turns):
        self._turns = list(turns)
        self.calls = 0

    def _next(self):
        self.calls += 1
        if not self._turns:
            raise AssertionError("loop asked for more turns than were scripted")
        return self._turns.pop(0)

    def chat(self, messages, tools):
        deltas, calls = self._next()
        return SimpleNamespace(content="".join(deltas), tool_calls=calls)

    def chat_stream(self, messages, tools, on_delta):
        deltas, calls = self._next()
        for d in deltas:
            on_delta(d)
        return SimpleNamespace(content="".join(deltas), tool_calls=calls)


def make_loop(tmp_path, llm, results=None, confirmer=lambda req: True):
    """Registry mirroring the real tools this feature discriminates between."""
    results = results or {}
    reg = ToolRegistry()

    def register(name, params, tier=RiskTier.UNDO):
        reg.register(
            Tool(
                name=name,
                description=name,
                parameters={"type": "object", "properties": params, "required": list(params)},
                risk_tier=tier,
                platforms=("darwin",),
                func=lambda args, _n=name: results.get(_n, "ok"),
            )
        )

    register("open_app", {"name": {"type": "string"}})
    register("quit_app", {"name": {"type": "string"}}, RiskTier.CONFIRM)
    register("set_volume", {"level": {"type": "integer"}})
    register("focus_window", {"name": {"type": "string"}})
    register("read_file", {"path": {"type": "string"}}, RiskTier.AUTO)

    gate = PermissionGate(ActionLog(tmp_path / "a.jsonl"), confirmer=confirmer)
    return AgentLoop(llm, reg, gate, platform="darwin")


# --- the phrase itself -------------------------------------------------------


def test_confirmation_names_the_app_so_the_user_knows_which_one_opened():
    """"Done" is useless when ASR may have heard the wrong app name."""
    assert "calculator" in confirmation_for("open_app", {"name": "Calculator"}, "ok").lower()


def test_confirmation_reports_the_level_that_was_actually_set():
    assert "30" in confirmation_for("set_volume", {"level": 30}, "ok")


def test_a_query_tool_has_no_canned_confirmation():
    """read_file's answer is its contents; no template can stand in for it."""
    assert confirmation_for("read_file", {"path": "x"}, "alpha beta") is None


def test_an_unknown_tool_has_no_canned_confirmation():
    assert confirmation_for("some_future_tool", {}, "ok") is None


@pytest.mark.parametrize("result", ["ERROR: no such app", "DENIED: the user did not approve this action."])
def test_a_failed_action_is_never_confirmed_as_success(result):
    """Speaking "Opening Chrome." when it did not open is the worst outcome."""
    assert confirmation_for("open_app", {"name": "Chrome"}, result) is None


# --- the loop ----------------------------------------------------------------


def test_a_successful_action_is_spoken_from_the_tool_result(tmp_path):
    # The model deliberately does NOT name the app here: if the assertion below
    # passes, the name can only have come from the tool arguments.
    llm = ScriptedLLM([
        ([], [tool_call("1", "open_app", {"name": "Calculator"})]),
        (["That is now open and ready."], None),
    ])
    loop = make_loop(tmp_path, llm)
    spoken = []

    loop.run("open the calculator", on_sentence=spoken.append)

    assert any("Calculator" in s for s in spoken), f"no confirmation spoken: {spoken}"


def test_the_models_redundant_narration_is_not_spoken_after_a_pure_action_turn(tmp_path):
    """This is the whole point: the user must not wait to hear a restatement."""
    llm = ScriptedLLM([
        ([], [tool_call("1", "open_app", {"name": "Calculator"})]),
        (["Calculator is now open and ready."], None),
    ])
    loop = make_loop(tmp_path, llm)
    spoken = []

    loop.run("open the calculator", on_sentence=spoken.append)

    assert not any("ready" in s for s in spoken), f"narration leaked: {spoken}"


def test_text_mode_returns_the_confirmation_so_it_is_still_reported(tmp_path):
    """Without on_sentence the caller speaks the return value; it cannot be blank."""
    llm = ScriptedLLM([
        ([], [tool_call("1", "open_app", {"name": "Calculator"})]),
        (["That is now open and ready."], None),
    ])
    loop = make_loop(tmp_path, llm)

    assert "Calculator" in loop.run("open the calculator")


def test_a_query_answer_still_comes_from_the_model(tmp_path):
    llm = ScriptedLLM([
        ([], [tool_call("1", "read_file", {"path": "x"})]),
        (["The first word is alpha."], None),
    ])
    loop = make_loop(tmp_path, llm, results={"read_file": "alpha beta"})
    spoken = []

    reply = loop.run("read the file", on_sentence=spoken.append)

    assert "alpha" in reply
    assert any("alpha" in s for s in spoken), f"query answer was suppressed: {spoken}"


def test_an_action_followed_by_a_query_keeps_the_query_answer(tmp_path):
    """Suppression must not swallow a later real answer in a multi-step turn."""
    llm = ScriptedLLM([
        ([], [tool_call("1", "open_app", {"name": "Calculator"})]),
        ([], [tool_call("2", "read_file", {"path": "x"})]),
        (["The first word is alpha."], None),
    ])
    loop = make_loop(tmp_path, llm, results={"read_file": "alpha beta"})
    spoken = []

    reply = loop.run("open calculator then read the file", on_sentence=spoken.append)

    assert llm.calls == 3, "the follow-up call must still happen for multi-step"
    assert "alpha" in reply
    assert any("Calculator" in s for s in spoken)
    assert any("alpha" in s for s in spoken)


def test_a_failed_action_lets_the_model_explain(tmp_path):
    """The user needs the reason, and only the model has it."""
    llm = ScriptedLLM([
        ([], [tool_call("1", "open_app", {"name": "Grom"})]),
        (["I could not find an app called Grom."], None),
    ])
    loop = make_loop(tmp_path, llm, results={"open_app": "ERROR: no such app"})
    spoken = []

    reply = loop.run("open grom", on_sentence=spoken.append)

    assert "could not find" in reply
    assert any("could not find" in s for s in spoken), f"error was suppressed: {spoken}"


def test_a_declined_confirmation_lets_the_model_explain(tmp_path):
    llm = ScriptedLLM([
        ([], [tool_call("1", "quit_app", {"name": "Safari"})]),
        (["I did not quit Safari."], None),
    ])
    loop = make_loop(tmp_path, llm, confirmer=lambda req: False)
    spoken = []

    reply = loop.run("quit safari", on_sentence=spoken.append)

    assert "did not quit" in reply
    assert any("did not quit" in s for s in spoken), f"denial was suppressed: {spoken}"


def test_a_plain_answer_with_no_tools_is_untouched(tmp_path):
    llm = ScriptedLLM([(["I can help with files. ", "And apps."], None)])
    loop = make_loop(tmp_path, llm)
    spoken = []

    reply = loop.run("what can you do?", on_sentence=spoken.append)

    assert reply == "I can help with files. And apps."
    assert spoken, "a no-tool answer must still stream"
