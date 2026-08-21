import os
from pathlib import Path

import pytest

from assistant.security.paths import PathNotAllowedError, resolve_safe


def test_inside_root_allowed(tmp_path: Path):
    (tmp_path / "docs").mkdir()
    p = resolve_safe(str(tmp_path / "docs"), [tmp_path])
    assert p == (tmp_path / "docs").resolve()


def test_root_itself_allowed(tmp_path: Path):
    assert resolve_safe(str(tmp_path), [tmp_path]) == tmp_path.resolve()


def test_outside_root_rejected(tmp_path: Path):
    with pytest.raises(PathNotAllowedError):
        resolve_safe("/etc/passwd", [tmp_path])


def test_dotdot_escape_rejected(tmp_path: Path):
    with pytest.raises(PathNotAllowedError):
        resolve_safe(str(tmp_path / ".." / ".."), [tmp_path])


def test_symlink_escape_rejected(tmp_path: Path):
    link = tmp_path / "link"
    os.symlink(tmp_path.parent, link)
    with pytest.raises(PathNotAllowedError):
        resolve_safe(str(link), [tmp_path])
