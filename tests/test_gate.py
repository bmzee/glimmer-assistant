import json
from pathlib import Path

from assistant.security.confirm import ConfirmRequest
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
    gate = PermissionGate(ActionLog(log_path), confirmer=lambda req: answer)
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
    gate = PermissionGate(ActionLog(log_path), confirmer=lambda req: asked.append(req) or True)
    assert gate.check(make_tool(RiskTier.NEVER), {}) is False
    assert asked == []
    assert decisions(log_path) == ["refused"]


def test_confirm_receives_structured_request(tmp_path):
    seen = []
    log = ActionLog(tmp_path / "a.jsonl")
    gate = PermissionGate(log, confirmer=lambda req: seen.append(req) or True)
    gate.check(make_tool(RiskTier.CONFIRM), {"command": "ls"})
    assert isinstance(seen[0], ConfirmRequest)
    assert seen[0].tool_name == "t"
    assert "ls" in seen[0].preview


def outbound_tool(tier):
    from assistant.tools.registry import RiskTier, Tool

    return Tool(
        name="send_mail",
        description="d",
        parameters={"type": "object", "properties": {}, "required": []},
        risk_tier=tier,
        platforms=("darwin",),
        func=lambda args: "sent",
        outbound=True,
    )


def test_outbound_auto_tier_is_elevated_after_untrusted_ingest(tmp_path):
    from assistant.security.trust import SessionTrust
    from assistant.security.gate import PermissionGate
    from assistant.security.log import ActionLog
    from assistant.tools.registry import RiskTier

    asked = []
    trust = SessionTrust()
    log_path = tmp_path / "a.jsonl"
    gate = PermissionGate(
        ActionLog(log_path),
        confirmer=lambda req: asked.append(req) or True,
        trust=trust,
    )
    tool = outbound_tool(RiskTier.AUTO)

    # before ingest: AUTO outbound runs without asking
    assert gate.check(tool, {}) is True
    assert asked == []

    # after ingesting untrusted content: the SAME tool must now be confirmed
    trust.note_untrusted_ingest("read_webpage")
    assert gate.check(tool, {}) is True
    assert len(asked) == 1

    records = [json.loads(l) for l in log_path.read_text().splitlines()]
    assert records[-1].get("elevated") is True


def test_non_outbound_tool_not_elevated(tmp_path):
    from assistant.security.trust import SessionTrust
    from assistant.security.gate import PermissionGate
    from assistant.security.log import ActionLog
    from assistant.tools.registry import RiskTier

    asked = []
    trust = SessionTrust()
    trust.note_untrusted_ingest("read_webpage")
    gate = PermissionGate(
        ActionLog(tmp_path / "a.jsonl"),
        confirmer=lambda req: asked.append(req) or True,
        trust=trust,
    )
    assert gate.check(make_tool(RiskTier.AUTO), {}) is True
    assert asked == []  # reading a file is not outbound; no elevation


def test_outbound_undo_tier_is_elevated_after_untrusted_ingest(tmp_path):
    # Same as the AUTO elevation test above, but for RiskTier.UNDO — elevation
    # must be tier-agnostic (any outbound tool, not just AUTO ones), so a
    # future refactor that special-cases AUTO can't silently regress UNDO.
    from assistant.security.trust import SessionTrust
    from assistant.security.gate import PermissionGate
    from assistant.security.log import ActionLog
    from assistant.tools.registry import RiskTier

    asked = []
    trust = SessionTrust()
    log_path = tmp_path / "a.jsonl"
    gate = PermissionGate(
        ActionLog(log_path),
        confirmer=lambda req: asked.append(req) or True,
        trust=trust,
    )
    tool = outbound_tool(RiskTier.UNDO)

    # before ingest: UNDO outbound runs without asking
    assert gate.check(tool, {}) is True
    assert asked == []

    # after ingesting untrusted content: the SAME tool must now be confirmed
    trust.note_untrusted_ingest("read_webpage")
    assert gate.check(tool, {}) is True
    assert len(asked) == 1

    records = [json.loads(l) for l in log_path.read_text().splitlines()]
    assert records[-1].get("elevated") is True


def test_elevated_confirm_request_is_flagged_and_names_the_ingesting_tool(tmp_path):
    # IMPORTANT-8: an elevated confirmation must not look identical to a
    # routine one — the human needs to see that untrusted content may have
    # induced this action, and which tool ingested it.
    from assistant.security.trust import SessionTrust
    from assistant.security.gate import PermissionGate
    from assistant.security.log import ActionLog
    from assistant.tools.registry import RiskTier

    seen = []
    trust = SessionTrust()
    trust.note_untrusted_ingest("read_mail_message")
    gate = PermissionGate(
        ActionLog(tmp_path / "a.jsonl"),
        confirmer=lambda req: seen.append(req) or True,
        trust=trust,
    )
    gate.check(outbound_tool(RiskTier.AUTO), {})

    assert len(seen) == 1
    assert seen[0].elevated is True
    assert "ELEVATED" in seen[0].preview
    assert "read_mail_message" in seen[0].preview


def test_non_elevated_confirm_request_has_no_elevation_marker(tmp_path):
    seen = []
    log = ActionLog(tmp_path / "a.jsonl")
    gate = PermissionGate(log, confirmer=lambda req: seen.append(req) or True)
    gate.check(make_tool(RiskTier.CONFIRM), {"command": "ls"})

    assert len(seen) == 1
    assert seen[0].elevated is False
    assert "ELEVATED" not in seen[0].preview


def test_elevated_denial_blocks(tmp_path):
    from assistant.security.trust import SessionTrust
    from assistant.security.gate import PermissionGate
    from assistant.security.log import ActionLog
    from assistant.tools.registry import RiskTier

    trust = SessionTrust()
    trust.note_untrusted_ingest("read_webpage")
    gate = PermissionGate(
        ActionLog(tmp_path / "a.jsonl"), confirmer=lambda req: False, trust=trust
    )
    assert gate.check(outbound_tool(RiskTier.AUTO), {}) is False
