import hashlib
import json
from types import SimpleNamespace

from assistant.agent.loop import AgentLoop
from assistant.security.gate import PermissionGate
from assistant.security.log import ActionLog
from assistant.tools.registry import RiskTier, Tool, ToolRegistry


class FakeLLM:
    def __init__(self, scripted):
        self._scripted = list(scripted)
        self.seen_messages = []

    def chat(self, messages, tools):
        self.seen_messages.append([dict(m) for m in messages])
        return self._scripted.pop(0)


def tool_call(call_id, name, arguments: dict):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
    )


def assistant_msg(content=None, tool_calls=None):
    return SimpleNamespace(content=content, tool_calls=tool_calls)


def make_registry(func, tier=RiskTier.AUTO):
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
    return reg


def make_loop(tmp_path, llm, registry, confirm=True, **kwargs):
    gate = PermissionGate(ActionLog(tmp_path / "a.jsonl"), confirmer=lambda req: confirm)
    return AgentLoop(llm, registry, gate, platform="darwin", **kwargs)


def test_plain_answer_no_tools(tmp_path):
    llm = FakeLLM([assistant_msg(content="hello there")])
    loop = make_loop(tmp_path, llm, make_registry(lambda a: "x"))
    assert loop.run("hi") == "hello there"


def test_tool_call_then_answer(tmp_path):
    seen_args = []

    def echo(args):
        seen_args.append(args)
        return "echoed!"

    llm = FakeLLM(
        [
            assistant_msg(tool_calls=[tool_call("c1", "echo", {"v": 1})]),
            assistant_msg(content="done"),
        ]
    )
    loop = make_loop(tmp_path, llm, make_registry(echo))
    assert loop.run("go") == "done"
    assert seen_args == [{"v": 1}]
    # second LLM call must include the tool result message
    tool_msgs = [m for m in llm.seen_messages[1] if m["role"] == "tool"]
    assert tool_msgs == [{"role": "tool", "tool_call_id": "c1", "content": "echoed!"}]


def test_denied_tool_not_executed(tmp_path):
    executed = []
    llm = FakeLLM(
        [
            assistant_msg(tool_calls=[tool_call("c1", "echo", {})]),
            assistant_msg(content="ok"),
        ]
    )
    registry = make_registry(lambda a: executed.append(a) or "x", tier=RiskTier.CONFIRM)
    loop = make_loop(tmp_path, llm, registry, confirm=False)
    loop.run("go")
    assert executed == []
    tool_msgs = [m for m in llm.seen_messages[1] if m["role"] == "tool"]
    assert tool_msgs[0]["content"] == "DENIED: the user did not approve this action."


def test_tool_exception_becomes_error_string(tmp_path):
    def boom(args):
        raise RuntimeError("kaput")

    llm = FakeLLM(
        [
            assistant_msg(tool_calls=[tool_call("c1", "echo", {})]),
            assistant_msg(content="ok"),
        ]
    )
    loop = make_loop(tmp_path, llm, make_registry(boom))
    loop.run("go")
    tool_msgs = [m for m in llm.seen_messages[1] if m["role"] == "tool"]
    assert tool_msgs[0]["content"].startswith("ERROR: kaput")


def test_unknown_tool(tmp_path):
    llm = FakeLLM(
        [
            assistant_msg(tool_calls=[tool_call("c1", "nope", {})]),
            assistant_msg(content="ok"),
        ]
    )
    loop = make_loop(tmp_path, llm, make_registry(lambda a: "x"))
    loop.run("go")
    tool_msgs = [m for m in llm.seen_messages[1] if m["role"] == "tool"]
    assert tool_msgs[0]["content"] == "ERROR: unknown tool nope"


def test_result_truncated(tmp_path):
    llm = FakeLLM(
        [
            assistant_msg(tool_calls=[tool_call("c1", "echo", {})]),
            assistant_msg(content="ok"),
        ]
    )
    loop = make_loop(
        tmp_path, llm, make_registry(lambda a: "z" * 100), tool_result_max_chars=10
    )
    loop.run("go")
    tool_msgs = [m for m in llm.seen_messages[1] if m["role"] == "tool"]
    assert tool_msgs[0]["content"] == "z" * 10 + "\n[truncated]"


def test_iteration_cap(tmp_path):
    endless = assistant_msg(tool_calls=[tool_call("c1", "echo", {})])
    llm = FakeLLM([endless, endless, endless])
    loop = make_loop(tmp_path, llm, make_registry(lambda a: "x"), max_iterations=3)
    out = loop.run("go")
    assert "step limit" in out


def test_parallel_tool_calls_both_executed(tmp_path):
    calls = []

    def echo(args):
        calls.append(args)
        return f"echoed {args}"

    llm = FakeLLM(
        [
            assistant_msg(
                tool_calls=[
                    tool_call("c1", "echo", {"v": 1}),
                    tool_call("c2", "echo", {"v": 2}),
                ]
            ),
            assistant_msg(content="done"),
        ]
    )
    loop = make_loop(tmp_path, llm, make_registry(echo))
    assert loop.run("go") == "done"
    assert calls == [{"v": 1}, {"v": 2}]
    tool_msgs = [m for m in llm.seen_messages[1] if m["role"] == "tool"]
    assert tool_msgs == [
        {"role": "tool", "tool_call_id": "c1", "content": "echoed {'v': 1}"},
        {"role": "tool", "tool_call_id": "c2", "content": "echoed {'v': 2}"},
    ]


def test_tool_returns_none(tmp_path):
    def returns_none(args):
        return None

    llm = FakeLLM(
        [
            assistant_msg(tool_calls=[tool_call("c1", "echo", {})]),
            assistant_msg(content="ok"),
        ]
    )
    loop = make_loop(tmp_path, llm, make_registry(returns_none))
    loop.run("go")
    tool_msgs = [m for m in llm.seen_messages[1] if m["role"] == "tool"]
    assert tool_msgs[0]["content"].startswith("ERROR:")


def test_untrusted_tool_result_is_datamarked(tmp_path):
    reg = ToolRegistry()
    reg.register(
        Tool(
            name="fetch",
            description="d",
            parameters={"type": "object", "properties": {}, "required": []},
            risk_tier=RiskTier.AUTO,
            platforms=("darwin",),
            func=lambda a: "secret instructions",
            untrusted=True,
        )
    )
    llm = FakeLLM(
        [
            assistant_msg(tool_calls=[tool_call("c1", "fetch", {})]),
            assistant_msg(content="done"),
        ]
    )
    loop = make_loop(tmp_path, llm, reg)
    loop.run("go")
    tool_msgs = [m for m in llm.seen_messages[1] if m["role"] == "tool"]
    assert "untrusted" in tool_msgs[0]["content"].lower()
    assert "secret instructions" in tool_msgs[0]["content"]


def test_post_execution_result_is_logged(tmp_path):
    log_path = tmp_path / "audit.jsonl"
    llm = FakeLLM(
        [
            assistant_msg(tool_calls=[tool_call("c1", "echo", {})]),
            assistant_msg(content="done"),
        ]
    )
    registry = make_registry(lambda a: "the-result")
    gate = PermissionGate(ActionLog(tmp_path / "gate.jsonl"), confirmer=lambda r: True)
    loop = AgentLoop(llm, registry, gate, platform="darwin", log=ActionLog(log_path))
    loop.run("go")

    records = [json.loads(l) for l in log_path.read_text().splitlines()]
    result_records = [r for r in records if r.get("event") == "tool_result"]
    assert len(result_records) == 1
    rec = result_records[0]
    assert rec["tool"] == "echo"
    assert rec["status"] == "ok"
    assert rec["result_sha256"] == hashlib.sha256(b"the-result").hexdigest()
