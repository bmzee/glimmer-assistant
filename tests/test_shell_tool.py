import subprocess
from pathlib import Path
from types import SimpleNamespace

from assistant.tools.shell import make_shell_tool
from assistant.tools.registry import RiskTier


def fake_runner(result):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return result

    run.calls = calls
    return run


def test_shell_tool_is_confirm_tier_darwin_only(tmp_path):
    tool = make_shell_tool([tmp_path], runner=fake_runner(SimpleNamespace(returncode=0, stdout="", stderr="")))
    assert tool.name == "run_shell"
    assert tool.risk_tier == RiskTier.CONFIRM
    assert tool.platforms == ("darwin",)


def test_shell_tool_wraps_and_reports(tmp_path, monkeypatch):
    monkeypatch.setattr("assistant.tools.shell.wrap_command", lambda argv, roots: ["SB", *argv])
    runner = fake_runner(SimpleNamespace(returncode=0, stdout="hello\n", stderr=""))
    tool = make_shell_tool([tmp_path], runner=runner)
    out = tool.func({"command": "echo hello"})
    # command was wrapped through the sandbox and run via /bin/sh -c
    argv = runner.calls[0][0]
    assert argv[0] == "SB"
    assert argv[-3:] == ["/bin/sh", "-c", "echo hello"]
    assert "hello" in out
    assert "0" in out  # exit code surfaced


def test_shell_tool_reports_nonzero_and_stderr(tmp_path, monkeypatch):
    monkeypatch.setattr("assistant.tools.shell.wrap_command", lambda argv, roots: ["SB", *argv])
    runner = fake_runner(SimpleNamespace(returncode=2, stdout="", stderr="boom"))
    tool = make_shell_tool([tmp_path], runner=runner)
    out = tool.func({"command": "false"})
    assert "boom" in out
    assert "2" in out


def test_shell_tool_exception_becomes_error(tmp_path, monkeypatch):
    def boom_runner(argv, **kwargs):
        raise subprocess.TimeoutExpired(cmd="x", timeout=60)
    monkeypatch.setattr("assistant.tools.shell.wrap_command", lambda argv, roots: ["SB", *argv])
    tool = make_shell_tool([tmp_path], runner=boom_runner)
    out = tool.func({"command": "sleep 999"})
    assert out.startswith("ERROR:")
