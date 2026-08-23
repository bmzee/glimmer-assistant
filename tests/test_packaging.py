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


# --- self-contained bundle (Plan 7) -----------------------------------------

def test_adhoc_signing_omits_hardened_runtime():
    """`--options runtime` makes the bundled app unlaunchable.

    Hardened runtime enables library validation. A PyInstaller bundle loads an
    embedded Python.framework signed separately, and two independently
    ad-hoc-signed binaries share no Team ID, so validation rejects the
    framework:

        Failed to load Python shared library ... different Team IDs

    Verified by building it both ways: with the flag the app exits 255 before
    running any Python; without it, it reaches the run loop. Hardened runtime
    is only a notarization requirement, and notarization needs a Developer ID
    an ad-hoc build does not have.
    """
    import inspect

    from appbundle import build_dist

    src = inspect.getsource(build_dist.sign)
    body = src.split('"""')[-1]  # ignore the docstring, which names the flag
    assert '"runtime"' not in body and "'runtime'" not in body, (
        "hardened runtime re-introduced into ad-hoc signing; the bundled app "
        "will fail to load its embedded Python framework"
    )


def test_collect_all_includes_the_data_only_transitive_deps():
    """language_tags and segments are why phonemization works when frozen.

    Neither is imported directly; both are data-only transitive deps of
    phonemizer. Without them the frozen app raises a FileNotFoundError naming
    neither package, which reads like an espeak failure and sends you hunting
    the wrong dylib.
    """
    from appbundle.build_dist import COLLECT_ALL

    for pkg in ("language_tags", "segments", "espeakng_loader", "mlx"):
        assert pkg in COLLECT_ALL, f"{pkg} missing from COLLECT_ALL"
