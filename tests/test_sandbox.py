import subprocess
import sys
from pathlib import Path

import pytest

from assistant.security.sandbox import (
    SandboxUnavailable,
    build_profile,
    sandbox_available,
    wrap_command,
)


def test_profile_denies_by_default_and_allows_listed_root(tmp_path: Path):
    profile = build_profile([tmp_path])
    assert "(deny default)" in profile
    assert "file-read*" in profile
    assert f'(subpath "{tmp_path.resolve()}")' in profile
    # no blanket network allow
    assert "allow network" not in profile


def test_wrap_command_shape(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("assistant.security.sandbox.sandbox_available", lambda: True)
    argv = wrap_command(["/bin/echo", "hi"], [tmp_path])
    assert argv[0] == "/usr/bin/sandbox-exec"
    assert argv[1] == "-f"
    assert Path(argv[2]).exists()
    assert argv[-2:] == ["/bin/echo", "hi"]


def test_wrap_raises_when_unavailable(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("assistant.security.sandbox.sandbox_available", lambda: False)
    with pytest.raises(SandboxUnavailable):
        wrap_command(["/bin/echo", "hi"], [tmp_path])


def test_build_profile_rejects_quote_in_root():
    with pytest.raises(ValueError, match="unsafe character in sandbox writable root"):
        build_profile([Path('/tmp/ev"il')])


def test_build_profile_rejects_backslash_in_root():
    with pytest.raises(ValueError, match="unsafe character in sandbox writable root"):
        build_profile([Path('/tmp/evil\\path')])


@pytest.mark.skipif(sys.platform != "darwin", reason="sandbox-exec is macOS-only")
def test_real_sandbox_confines_writes(tmp_path: Path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    # write inside allowed root: succeeds
    ok = subprocess.run(
        wrap_command(["/bin/sh", "-c", f"echo hi > {allowed}/ok.txt"], [allowed]),
        capture_output=True, text=True,
    )
    assert ok.returncode == 0, ok.stderr
    assert (allowed / "ok.txt").read_text().strip() == "hi"
    # write outside allowed root: denied, file never created
    denied_path = tmp_path / "denied.txt"
    bad = subprocess.run(
        wrap_command(["/bin/sh", "-c", f"echo nope > {denied_path}"], [allowed]),
        capture_output=True, text=True,
    )
    assert bad.returncode != 0
    assert not denied_path.exists()
