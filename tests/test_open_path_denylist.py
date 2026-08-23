"""open_path must deny by default: the blocklist was allow-by-omission.

A red-team re-attack proved the extension BLOCKLIST could be walked around.
`.terminal` is an ordinary plist with no execute bit, so it passed both the
blocklist and the exec-bit check -- and Terminal.app auto-runs the file's
CommandString on open. Arbitrary code execution outside the sandbox was
demonstrated end to end through the real tool.

The bug was structural, not a missing entry: enumerating dangerous types means
every type nobody listed is permitted. macOS hands many extensions to an
executing LaunchServices handler (.terminal, .webloc, .pkg, .inetloc, .url ...)
and the set cannot be completed by hand. These tests pin the inverted rule --
allowlist known-inert document types, refuse everything else -- which is the
same deny-default posture the SBPL sandbox profile already uses.
"""
from pathlib import Path

from assistant.tools.adapters.base import PlatformAdapter
from assistant.tools.apps import make_app_tools


class FakeAdapter(PlatformAdapter):
    def __init__(self):
        self.calls: list[tuple] = []

    def launch_app(self, name: str) -> str:
        self.calls.append(("launch_app", name))
        return "launched"

    def open_path(self, path: str) -> str:
        self.calls.append(("open_path", path))
        return f"opened {path}"

    def quit_app(self, name: str) -> str:
        return "quit"

    def list_windows(self) -> str:
        return "none"

    def focus_window(self, name: str) -> str:
        return "focused"

    def set_volume(self, level: int) -> str:
        return "set"

    def screenshot(self, path: str) -> str:
        return "saved"


def _tool(tmp_path):
    adapter = FakeAdapter()
    tools = {t.name: t for t in make_app_tools(adapter, [tmp_path])}
    return tools["open_path"], adapter


EXECUTING_TYPES = [
    "payload.terminal",     # Terminal profile: CommandString runs on open
    "link.webloc",          # opens an arbitrary URL
    "installer.pkg",        # launches the privileged installer
    "installer.mpkg",
    "disk.dmg",             # mounts a volume
    "link.inetloc",
    "link.url",
    "script.applescript",
]


def test_refuses_launchservices_executing_types(tmp_path: Path):
    """Each reaches an executing handler; none was in the old blocklist."""
    for name in EXECUTING_TYPES:
        target = tmp_path / name
        target.write_text("payload")
        tool, adapter = _tool(tmp_path)
        out = tool.func({"path": str(target)})
        assert out.startswith("ERROR:"), f"{name} was NOT refused"
        assert adapter.calls == [], f"{name} reached the adapter"


def test_refuses_unknown_extensions_by_default(tmp_path: Path):
    """The core inversion: a type nobody enumerated must be refused.

    This is what makes the guard survive the next macOS release that adds a
    new executing type.
    """
    target = tmp_path / "novel.somethingnobodythoughtof"
    target.write_text("x")
    tool, adapter = _tool(tmp_path)
    assert tool.func({"path": str(target)}).startswith("ERROR:")
    assert adapter.calls == []


def test_refuses_extensionless_files(tmp_path: Path):
    """No suffix means no way to know the handler; a Mach-O binary has none."""
    target = tmp_path / "payload"
    target.write_text("x")
    tool, adapter = _tool(tmp_path)
    assert tool.func({"path": str(target)}).startswith("ERROR:")
    assert adapter.calls == []


def test_still_opens_ordinary_documents(tmp_path: Path):
    """Deny-by-default must not make the tool useless."""
    for name in ("notes.txt", "report.pdf", "photo.png", "sheet.xlsx", "readme.md"):
        target = tmp_path / name
        target.write_text("x")
        tool, adapter = _tool(tmp_path)
        out = tool.func({"path": str(target)})
        assert not out.startswith("ERROR:"), f"{name} wrongly refused: {out}"
        assert adapter.calls[0][0] == "open_path"


def test_still_opens_plain_directories(tmp_path: Path):
    folder = tmp_path / "Downloads"
    folder.mkdir()
    tool, adapter = _tool(tmp_path)
    assert not tool.func({"path": str(folder)}).startswith("ERROR:")
    assert adapter.calls[0][0] == "open_path"


def test_refuses_bundle_shaped_directories(tmp_path: Path):
    """An .app is a DIRECTORY, so the exec-bit check skips it entirely."""
    for name in ("Evil.app", "Flow.workflow", "Thing.bundle"):
        bundle = tmp_path / name
        (bundle / "Contents" / "MacOS").mkdir(parents=True)
        tool, adapter = _tool(tmp_path)
        assert tool.func({"path": str(bundle)}).startswith("ERROR:"), name
        assert adapter.calls == []


def test_extension_matching_is_case_insensitive(tmp_path: Path):
    """APFS is case-insensitive: Foo.TERMINAL executes like foo.terminal."""
    target = tmp_path / "payload.TERMINAL"
    target.write_text("x")
    tool, adapter = _tool(tmp_path)
    assert tool.func({"path": str(target)}).startswith("ERROR:")
    assert adapter.calls == []


def test_executable_bit_still_refused_even_for_allowed_suffix(tmp_path: Path):
    """A .txt with +x is still handed to an executor by some handlers."""
    import stat as _stat

    target = tmp_path / "notes.txt"
    target.write_text("x")
    target.chmod(target.stat().st_mode | _stat.S_IXUSR)
    tool, adapter = _tool(tmp_path)
    assert tool.func({"path": str(target)}).startswith("ERROR:")
    assert adapter.calls == []
