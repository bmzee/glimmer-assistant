from pathlib import Path

import pytest

from assistant.tools.adapters.mac import MacAdapter
from assistant.tools.adapters.base import PlatformAdapter
from assistant.tools.apps import make_app_tools
from assistant.tools.registry import RiskTier


class FakeAdapter(PlatformAdapter):
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def launch_app(self, name: str) -> str:
        self.calls.append(("launch_app", name))
        return f"launched {name}"

    def open_path(self, path: str) -> str:
        self.calls.append(("open_path", path))
        return f"opened {path}"

    # The remaining PlatformAdapter methods are unused here but must exist:
    # the ABC now covers the full spec SS7 surface, and a fake that lags the
    # real interface is exactly how drift hides.
    def quit_app(self, name: str) -> str:
        self.calls.append(("quit_app", name))
        return f"quit {name}"

    def list_windows(self) -> str:
        self.calls.append(("list_windows",))
        return "no visible windows"

    def focus_window(self, name: str) -> str:
        self.calls.append(("focus_window", name))
        return f"focused {name}"

    def set_volume(self, level: int) -> str:
        self.calls.append(("set_volume", level))
        return f"volume set to {level}"

    def screenshot(self, path: str) -> str:
        self.calls.append(("screenshot", path))
        return f"screenshot saved to {path}"


def by_name(tools):
    return {t.name: t for t in tools}


def test_open_app_delegates_to_adapter(tmp_path: Path):
    adapter = FakeAdapter()
    tools = by_name(make_app_tools(adapter, [tmp_path]))
    assert tools["open_app"].func({"name": "Notes"}) == "launched Notes"
    assert adapter.calls == [("launch_app", "Notes")]


def test_open_path_checks_allowlist(tmp_path: Path):
    adapter = FakeAdapter()
    tools = by_name(make_app_tools(adapter, [tmp_path]))
    result = tools["open_path"].func({"path": "/etc/passwd"})
    assert result.startswith("ERROR:")
    assert adapter.calls == []


def test_open_path_inside_root(tmp_path: Path):
    (tmp_path / "doc.txt").write_text("x")
    adapter = FakeAdapter()
    tools = by_name(make_app_tools(adapter, [tmp_path]))
    out = tools["open_path"].func({"path": str(tmp_path / "doc.txt")})
    assert out.startswith("opened ")
    assert adapter.calls[0][0] == "open_path"


def test_tiers():
    adapter = FakeAdapter()
    tools = by_name(make_app_tools(adapter, []))
    # open_app targets an installed application by name -- narrow surface.
    assert tools["open_app"].risk_tier == RiskTier.UNDO
    # open_path crosses the sandbox boundary (`open` is NOT sandbox-exec
    # wrapped, unlike run_shell) and macOS `open` EXECUTES several file
    # types. UNDO would be silently auto-approved by the gate.
    assert tools["open_path"].risk_tier == RiskTier.CONFIRM


@pytest.mark.parametrize(
    "name",
    [
        "payload.command",
        "payload.COMMAND",  # APFS is case-insensitive: Foo.COMMAND still executes
        "payload.tool",
        "payload.scpt",
        "payload.sh",
        "payload.zsh",
        "payload.bash",
    ],
)
def test_open_path_refuses_executable_file_types(tmp_path: Path, name: str):
    """macOS `open` executes these instead of viewing them: a git-cloned repo
    preserves +x and carries no quarantine attr, so Gatekeeper never prompts.
    Opening one is arbitrary code execution outside the sandbox -- refuse."""
    target = tmp_path / name
    target.write_text("#!/bin/sh\necho pwned\n")
    adapter = FakeAdapter()
    tools = by_name(make_app_tools(adapter, [tmp_path]))
    result = tools["open_path"].func({"path": str(target)})
    assert result.startswith("ERROR:")
    assert adapter.calls == []


@pytest.mark.parametrize("name", ["Evil.app", "Evil.workflow"])
def test_open_path_refuses_executable_bundles(tmp_path: Path, name: str):
    """Bundles are directories; `open` launches them as programs."""
    (tmp_path / name).mkdir()
    adapter = FakeAdapter()
    tools = by_name(make_app_tools(adapter, [tmp_path]))
    result = tools["open_path"].func({"path": str(tmp_path / name)})
    assert result.startswith("ERROR:")
    assert adapter.calls == []


def test_open_path_refuses_user_executable_bit(tmp_path: Path):
    """Extension allowlists are bypassable (a Mach-O binary needs none);
    the +x bit is what makes `open` run a file, so refuse on the bit itself."""
    target = tmp_path / "innocent_notes"
    target.write_text("#!/bin/sh\necho pwned\n")
    target.chmod(0o755)
    adapter = FakeAdapter()
    tools = by_name(make_app_tools(adapter, [tmp_path]))
    result = tools["open_path"].func({"path": str(target)})
    assert result.startswith("ERROR:")
    assert adapter.calls == []


def test_open_path_still_opens_plain_documents(tmp_path: Path):
    target = tmp_path / "doc.md"
    target.write_text("hello")
    target.chmod(0o644)
    adapter = FakeAdapter()
    tools = by_name(make_app_tools(adapter, [tmp_path]))
    out = tools["open_path"].func({"path": str(target)})
    assert out.startswith("opened ")
    assert adapter.calls == [("open_path", str(target))]


def test_open_path_opens_plain_directories(tmp_path: Path):
    """Directories always carry +x (traversal); only bundles are dangerous."""
    sub = tmp_path / "projects"
    sub.mkdir()
    adapter = FakeAdapter()
    tools = by_name(make_app_tools(adapter, [tmp_path]))
    out = tools["open_path"].func({"path": str(sub)})
    assert out.startswith("opened ")
    assert adapter.calls == [("open_path", str(sub))]


def test_mac_adapter_launch_app_handles_oserror(monkeypatch):
    """MacAdapter catches OSError from subprocess.run and returns ERROR string."""
    adapter = MacAdapter()
    monkeypatch.setattr(
        "assistant.tools.adapters.mac.subprocess.run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            FileNotFoundError("open binary not found")
        ),
    )
    result = adapter.launch_app("Notes")
    assert result.startswith("ERROR:")
    assert isinstance(result, str)


def test_mac_adapter_open_path_handles_oserror(monkeypatch):
    """MacAdapter catches OSError from subprocess.run and returns ERROR string."""
    adapter = MacAdapter()
    monkeypatch.setattr(
        "assistant.tools.adapters.mac.subprocess.run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            OSError("subprocess error")
        ),
    )
    result = adapter.open_path("/some/path")
    assert result.startswith("ERROR:")
    assert isinstance(result, str)
