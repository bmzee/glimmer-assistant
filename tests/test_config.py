from pathlib import Path

from assistant.config import Config, load_config


def test_defaults_without_file():
    cfg = load_config(None)
    assert cfg.llm_base_url == "http://localhost:11434/v1"
    assert cfg.llm_model == "muse-glimmer:30b"
    assert cfg.max_iterations == 15
    assert cfg.tool_result_max_chars == 16000
    assert cfg.allowed_roots == ["~"]


def test_yaml_overrides(tmp_path: Path):
    f = tmp_path / "config.yaml"
    f.write_text("llm_model: qwen3.8:27b\nmax_iterations: 5\n")
    cfg = load_config(f)
    assert cfg.llm_model == "qwen3.8:27b"
    assert cfg.max_iterations == 5
    assert cfg.llm_base_url == "http://localhost:11434/v1"  # untouched default


def test_unknown_keys_ignored(tmp_path: Path):
    f = tmp_path / "config.yaml"
    f.write_text("not_a_real_key: 1\n")
    cfg = load_config(f)
    assert not hasattr(cfg, "not_a_real_key")
