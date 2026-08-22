from assistant.config import Config
from assistant.main import build_loop


def test_build_loop_darwin_registers_expected_tools(tmp_path):
    cfg = Config(allowed_roots=[str(tmp_path)], log_path=str(tmp_path / "a.jsonl"))
    loop = build_loop(cfg, confirmer=lambda req: False, platform="darwin")
    names = {t.name for t in loop._registry.available("darwin")}
    assert names == {"list_dir", "read_file", "open_app", "open_path"}


def test_build_loop_win32_gets_cross_platform_tools_only(tmp_path):
    cfg = Config(allowed_roots=[str(tmp_path)], log_path=str(tmp_path / "a.jsonl"))
    loop = build_loop(cfg, confirmer=lambda req: False, platform="win32")
    names = {t.name for t in loop._registry.available("win32")}
    # win32 has no adapter yet (Plan 2+), so only stdlib file tools register
    assert names == {"list_dir", "read_file"}
