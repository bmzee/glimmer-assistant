from pathlib import Path

import pytest

from assistant.security.paths import PathNotAllowedError
from assistant.tools.files import make_files_tools
from assistant.tools.registry import RiskTier


def by_name(tools):
    return {t.name: t for t in tools}


def test_list_dir(tmp_path: Path):
    (tmp_path / "b.txt").write_text("hi")
    (tmp_path / "adir").mkdir()
    tools = by_name(make_files_tools([tmp_path]))
    out = tools["list_dir"].func({"path": str(tmp_path)})
    assert out == "adir/\nb.txt"


def test_read_file(tmp_path: Path):
    (tmp_path / "b.txt").write_text("hello")
    tools = by_name(make_files_tools([tmp_path]))
    assert tools["read_file"].func({"path": str(tmp_path / "b.txt")}) == "hello"


def test_read_outside_root_raises(tmp_path: Path):
    tools = by_name(make_files_tools([tmp_path]))
    with pytest.raises(PathNotAllowedError):
        tools["read_file"].func({"path": "/etc/passwd"})


def test_tools_are_auto_tier_and_cross_platform(tmp_path: Path):
    for tool in make_files_tools([tmp_path]):
        assert tool.risk_tier == RiskTier.AUTO
        assert tool.platforms == ("darwin", "win32")
