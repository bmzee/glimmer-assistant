import json
from pathlib import Path

from assistant.security.gate import PermissionGate
from assistant.security.log import ActionLog
from assistant.tools.registry import RiskTier, Tool


def make_tool(tier: RiskTier) -> Tool:
    return Tool(
        name="t",
        description="d",
        parameters={"type": "object", "properties": {}, "required": []},
        risk_tier=tier,
        platforms=("darwin",),
        func=lambda args: "ok",
    )


def make_gate(tmp_path: Path, answer: bool):
    log_path = tmp_path / "a.jsonl"
    gate = PermissionGate(ActionLog(log_path), confirmer=lambda desc: answer)
    return gate, log_path


def decisions(log_path: Path) -> list[str]:
    return [json.loads(l)["decision"] for l in log_path.read_text().splitlines()]


def test_auto_allowed_and_logged(tmp_path):
    gate, log_path = make_gate(tmp_path, answer=False)
    assert gate.check(make_tool(RiskTier.AUTO), {"x": 1}) is True
    assert decisions(log_path) == ["auto"]


def test_undo_allowed(tmp_path):
    gate, _ = make_gate(tmp_path, answer=False)
    assert gate.check(make_tool(RiskTier.UNDO), {}) is True


def test_confirm_respects_answer(tmp_path):
    gate_yes, path_yes = make_gate(tmp_path, answer=True)
    assert gate_yes.check(make_tool(RiskTier.CONFIRM), {}) is True
    assert decisions(path_yes) == ["confirmed"]

    gate_no, path_no = make_gate(tmp_path / "no", answer=False)
    assert gate_no.check(make_tool(RiskTier.CONFIRM), {}) is False
    assert decisions(path_no) == ["denied"]


def test_never_refused_without_asking(tmp_path):
    asked = []
    log_path = tmp_path / "a.jsonl"
    gate = PermissionGate(ActionLog(log_path), confirmer=lambda d: asked.append(d) or True)
    assert gate.check(make_tool(RiskTier.NEVER), {}) is False
    assert asked == []
    assert decisions(log_path) == ["refused"]
