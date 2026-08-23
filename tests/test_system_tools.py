"""System-control tools closing the PlatformAdapter gap.

docs/spec.md SS7 specifies an eight-method PlatformAdapter; only launch_app and
open_path were built (see docs/spec-coverage.md). These cover the rest of the
user-visible surface: quit an app, list and focus windows, set the volume, take
a screenshot.

Risk tiers follow SS8.3. Note quit_app is CONFIRM rather than the UNDO its blast
radius would suggest: SS8.3's Tier-1 undo window does not exist yet, and quitting
an app with unsaved work is not recoverable without one.
"""
from pathlib import Path

from assistant.tools.adapters.base import PlatformAdapter
from assistant.tools.registry import RiskTier
from assistant.tools.system import CAPTURE_SUBDIR, make_system_tools


class FakeAdapter(PlatformAdapter):
    def __init__(self, result="ok"):
        self.calls: list[tuple] = []
        self.result = result

    def launch_app(self, name: str) -> str:
        self.calls.append(("launch_app", name))
        return "launched"

    def open_path(self, path: str) -> str:
        self.calls.append(("open_path", path))
        return "opened"

    def quit_app(self, name: str) -> str:
        self.calls.append(("quit_app", name))
        return self.result

    def list_windows(self) -> str:
        self.calls.append(("list_windows",))
        return self.result

    def focus_window(self, name: str) -> str:
        self.calls.append(("focus_window", name))
        return self.result

    def set_volume(self, level: int) -> str:
        self.calls.append(("set_volume", level))
        return self.result

    def screenshot(self, path: str) -> str:
        self.calls.append(("screenshot", path))
        return self.result


def by_name(tools):
    return {t.name: t for t in tools}


def tools_for(tmp_path, adapter=None):
    return by_name(make_system_tools(adapter or FakeAdapter(), [tmp_path]))


def test_quit_app_delegates(tmp_path: Path):
    adapter = FakeAdapter("quit Notes")
    assert tools_for(tmp_path, adapter)["quit_app"].func({"name": "Notes"}) == "quit Notes"
    assert adapter.calls == [("quit_app", "Notes")]


def test_quit_app_requires_confirmation(tmp_path: Path):
    """No undo window exists yet, and quitting can lose unsaved work."""
    assert tools_for(tmp_path)["quit_app"].risk_tier == RiskTier.CONFIRM


def test_list_windows_is_read_only(tmp_path: Path):
    assert tools_for(tmp_path)["list_windows"].risk_tier == RiskTier.AUTO


def test_focus_window_delegates(tmp_path: Path):
    adapter = FakeAdapter("focused Safari")
    out = tools_for(tmp_path, adapter)["focus_window"].func({"name": "Safari"})
    assert out == "focused Safari"
    assert adapter.calls == [("focus_window", "Safari")]


def test_set_volume_accepts_valid_range(tmp_path: Path):
    adapter = FakeAdapter("volume set to 40")
    out = tools_for(tmp_path, adapter)["set_volume"].func({"level": 40})
    assert out == "volume set to 40"
    assert adapter.calls == [("set_volume", 40)]


def test_set_volume_rejects_out_of_range_before_touching_the_system(tmp_path: Path):
    """A model producing 500 must not reach osascript."""
    adapter = FakeAdapter()
    tools = tools_for(tmp_path, adapter)
    for bad in (-1, 101, 500):
        assert tools["set_volume"].func({"level": bad}).startswith("ERROR:")
    assert adapter.calls == []


def test_set_volume_rejects_non_numeric(tmp_path: Path):
    adapter = FakeAdapter()
    out = tools_for(tmp_path, adapter)["set_volume"].func({"level": "loud"})
    assert out.startswith("ERROR:")
    assert adapter.calls == []


def test_screenshot_saves_bare_filename_into_capture_folder(tmp_path: Path):
    """A plain 'take a screenshot' must keep working: a bare file name lands
    in the dedicated capture folder, created on demand."""
    adapter = FakeAdapter("saved")
    out = tools_for(tmp_path, adapter)["screenshot"].func({"path": "shot.png"})
    assert not out.startswith("ERROR:")
    expected = tmp_path.resolve() / CAPTURE_SUBDIR / "shot.png"
    assert adapter.calls == [("screenshot", str(expected))]
    assert expected.parent.is_dir()


def test_screenshot_accepts_absolute_path_inside_capture_folder(tmp_path: Path):
    adapter = FakeAdapter("saved")
    target = tmp_path / CAPTURE_SUBDIR / "shot.png"
    out = tools_for(tmp_path, adapter)["screenshot"].func({"path": str(target)})
    assert not out.startswith("ERROR:")
    assert adapter.calls[0][0] == "screenshot"


def test_screenshot_refuses_paths_outside_allowed_roots(tmp_path: Path):
    """Model-supplied paths are canonicalized and allowlisted (spec SS8.4)."""
    adapter = FakeAdapter()
    out = tools_for(tmp_path, adapter)["screenshot"].func({"path": "/etc/evil.png"})
    assert out.startswith("ERROR:")
    assert adapter.calls == []


def test_screenshot_refuses_traversal_escape(tmp_path: Path):
    adapter = FakeAdapter()
    out = tools_for(tmp_path, adapter)["screenshot"].func({"path": "../escape.png"})
    assert out.startswith("ERROR:")
    assert adapter.calls == []


def test_screenshot_confined_to_capture_folder(tmp_path: Path):
    """Being inside an allowed root is no longer enough: injected content must
    not be able to aim the write primitive at arbitrary user documents."""
    adapter = FakeAdapter()
    out = tools_for(tmp_path, adapter)["screenshot"].func(
        {"path": str(tmp_path / "Documents" / "thesis.png")}
    )
    assert out.startswith("ERROR:")
    assert adapter.calls == []


def test_screenshot_refuses_non_png_suffix(tmp_path: Path):
    """actions.jsonl, .zshrc, thesis.docx: every non-.png target is refused
    before the adapter runs."""
    adapter = FakeAdapter()
    tools = tools_for(tmp_path, adapter)
    for name in ("shot.jpg", "actions.jsonl", "noext"):
        target = str(tmp_path / CAPTURE_SUBDIR / name)
        assert tools["screenshot"].func({"path": target}).startswith("ERROR:")
    assert adapter.calls == []


def test_screenshot_refuses_to_overwrite_existing_file(tmp_path: Path):
    """screencapture truncates its target; an existing file must never be
    clobberable, even inside the capture folder."""
    adapter = FakeAdapter()
    existing = tmp_path / CAPTURE_SUBDIR / "shot.png"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"prior contents")
    out = tools_for(tmp_path, adapter)["screenshot"].func({"path": str(existing)})
    assert out.startswith("ERROR:")
    assert adapter.calls == []
    assert existing.read_bytes() == b"prior contents"


def test_screenshot_denylist_refuses_protected_paths(tmp_path: Path):
    """Defense in depth: even a capture dir misconfigured to contain the audit
    log must not allow a write over it."""
    adapter = FakeAdapter()
    log = tmp_path / "actions.png"  # worst case: a log the suffix check would pass
    tools = by_name(
        make_system_tools(
            adapter, [tmp_path], capture_dir=tmp_path, protected_paths=[log]
        )
    )
    out = tools["screenshot"].func({"path": str(log)})
    assert out.startswith("ERROR:")
    assert "protected" in out
    assert adapter.calls == []


def test_screenshot_always_refuses_glimmer_config_dir(tmp_path: Path):
    """~/.glimmer-assistant (audit log + config) is denied unconditionally,
    even when the capture dir is (mis)configured to be all of home."""
    adapter = FakeAdapter()
    home = Path.home()
    tools = by_name(make_system_tools(adapter, [home], capture_dir=home))
    out = tools["screenshot"].func(
        {"path": str(home / ".glimmer-assistant" / "evil.png")}
    )
    assert out.startswith("ERROR:")
    assert "protected" in out
    assert adapter.calls == []


def test_build_loop_wires_configured_audit_log_into_denylist(
    tmp_path: Path, monkeypatch
):
    """The finding's exact attack, end to end: a screenshot steered at the
    configured actions log is refused as protected, not merely misplaced."""
    from assistant.config import Config
    from assistant.main import build_loop
    from assistant.tools.adapters.mac import MacAdapter

    calls: list[str] = []
    monkeypatch.setattr(
        MacAdapter, "screenshot", lambda self, path: (calls.append(path), "saved")[1]
    )
    cfg = Config(
        allowed_roots=[str(tmp_path)],
        log_path=str(tmp_path / "actions.jsonl"),
        enable_web=False,
        enable_apple=False,
    )
    loop = build_loop(cfg, lambda r: False, "darwin")
    tools = {t.name: t for t in loop._registry.available("darwin")}
    out = tools["screenshot"].func({"path": str(tmp_path / "actions.jsonl")})
    assert out.startswith("ERROR:")
    assert "protected" in out
    assert calls == []


def test_all_system_tools_are_darwin_scoped(tmp_path: Path):
    """Registry hides unavailable tools; these are AppleScript-backed."""
    for tool in make_system_tools(FakeAdapter(), [tmp_path]):
        assert tool.platforms == ("darwin",)


def test_adapter_errors_are_returned_not_raised(tmp_path: Path):
    class Boom(FakeAdapter):
        def quit_app(self, name):
            raise OSError("no such app")

    out = tools_for(tmp_path, Boom())["quit_app"].func({"name": "Ghost"})
    assert out.startswith("ERROR:")
