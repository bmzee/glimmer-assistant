"""Plan 6: a .app bundle so the assistant owns its own TCC permissions.

Module is `appbundle`, not `packaging`: the latter is a real PyPI
distribution (a setuptools/pytest dependency) already installed here, and
a local module of that name would shadow it.

macOS attaches Automation / Microphone / Screen Recording consent to the
*responsible process* -- the launcher. Run from a terminal, that is the
terminal, which is why the assistant currently borrows Claude Code's grants.
In production it must be its own bundle with its own identifier, or the user
cannot grant (or revoke) permissions to *the assistant* at all.

These tests cover what is checkable offline: bundle layout, the Info.plist
keys macOS requires before it will even show a consent prompt, and the
launcher. Whether TCC actually attributes to the bundle is verified live --
no unit test can prove that.
"""
import plistlib
import stat

from appbundle.build_app import build_bundle


def build(tmp_path, **kw):
    return build_bundle(tmp_path / "GlimmerAssistant.app", **kw)


def plist_of(app):
    return plistlib.loads((app / "Contents" / "Info.plist").read_bytes())


def test_bundle_has_the_standard_layout(tmp_path):
    app = build(tmp_path)
    assert (app / "Contents" / "Info.plist").is_file()
    assert (app / "Contents" / "MacOS").is_dir()


def test_executable_named_in_plist_actually_exists(tmp_path):
    """A plist naming a missing binary produces an app that silently won't launch."""
    app = build(tmp_path)
    name = plist_of(app)["CFBundleExecutable"]
    assert (app / "Contents" / "MacOS" / name).is_file()


def test_launcher_is_executable(tmp_path):
    app = build(tmp_path)
    name = plist_of(app)["CFBundleExecutable"]
    mode = (app / "Contents" / "MacOS" / name).stat().st_mode
    assert mode & stat.S_IXUSR


def test_has_its_own_stable_bundle_identifier(tmp_path):
    """The identifier IS the TCC identity. It must not collide with a terminal."""
    ident = plist_of(build(tmp_path))["CFBundleIdentifier"]
    assert ident == "com.glimmer.assistant"
    assert "terminal" not in ident.lower()


def test_declares_microphone_usage(tmp_path):
    """Without this key macOS kills the process instead of prompting."""
    text = plist_of(build(tmp_path))["NSMicrophoneUsageDescription"]
    assert text and "push-to-talk" in text.lower()


def test_declares_apple_events_usage(tmp_path):
    """Required before Mail/Calendar/System Events control can be granted."""
    text = plist_of(build(tmp_path))["NSAppleEventsUsageDescription"]
    assert text
    assert any(app in text for app in ("Mail", "Calendar"))


def test_usage_strings_say_why_not_just_what(tmp_path):
    """The user reads these in the consent dialog; they are the only context."""
    p = plist_of(build(tmp_path))
    for key in ("NSMicrophoneUsageDescription", "NSAppleEventsUsageDescription"):
        assert len(p[key]) > 40, f"{key} is too terse to inform consent"


def test_launcher_invokes_the_configured_interpreter_and_module(tmp_path):
    app = build(tmp_path, python="/opt/venv/bin/python", args=["--voice"])
    script = (app / "Contents" / "MacOS" / "glimmer-assistant").read_text()
    assert "/opt/venv/bin/python" in script
    assert "assistant" in script
    assert "--voice" in script


def test_launcher_quotes_paths_containing_spaces(tmp_path):
    """~/Library/Application Support and friends contain spaces."""
    app = build(tmp_path, python="/Users/a b/venv/bin/python")
    script = (app / "Contents" / "MacOS" / "glimmer-assistant").read_text()
    assert '"/Users/a b/venv/bin/python"' in script


def test_rebuild_is_idempotent(tmp_path):
    """Rebuilding must not accumulate or fail on an existing bundle."""
    first = build(tmp_path)
    ident_before = plist_of(first)["CFBundleIdentifier"]
    second = build(tmp_path)
    assert plist_of(second)["CFBundleIdentifier"] == ident_before
    assert second == first


def test_bundle_declares_a_version(tmp_path):
    p = plist_of(build(tmp_path))
    assert p["CFBundleShortVersionString"]
    assert p["CFBundlePackageType"] == "APPL"
