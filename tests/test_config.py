from pathlib import Path

import pytest

from assistant.config import Config, load_config


def test_defaults_without_file():
    cfg = load_config(None)
    assert cfg.llm_base_url == "http://localhost:11434/v1"
    # Default selected by the A/B in docs/model-ab.md (both 10/10; Qwen chosen for
    # tool discipline, not speed -- Glimmer is actually faster per token)
    assert cfg.llm_model == "qwen3.8:27b"
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


def test_allowed_roots_scalar_string_is_wrapped(tmp_path: Path):
    f = tmp_path / "config.yaml"
    f.write_text("allowed_roots: /tmp/x\n")
    cfg = load_config(f)
    assert cfg.allowed_roots == ["/tmp/x"]


def test_allowed_roots_invalid_type_raises(tmp_path: Path):
    f = tmp_path / "config.yaml"
    f.write_text("allowed_roots: 42\n")
    with pytest.raises(ValueError):
        load_config(f)


def test_llm_timeout_default():
    assert load_config(None).llm_timeout_seconds == 120.0


def test_voice_config_defaults():
    cfg = load_config(None)
    assert cfg.voice_stt_model == "mlx-community/parakeet-tdt-0.6b-v2"
    assert cfg.voice_tts_voice == "af_heart"
    # Right Option: reachable, and not a modifier used by ordinary shortcuts.
    assert cfg.voice_hotkey == "alt_r"
    assert cfg.voice_min_utterance_seconds == 0.3


def test_voice_activation_defaults_to_click():
    """Click is the only mode that needs no permission.

    Both hotkey modes require Input Monitoring; while that is ungranted the key
    silently does nothing and the app appears completely dead. A menu-bar
    button is our own UI receiving our own click.
    """
    cfg = load_config(None)
    assert cfg.voice_activation == "click"
    assert cfg.voice_tap_window_seconds == 0.4
    # A toggle can be left on in a way push-to-talk cannot; it must self-stop.
    assert cfg.voice_max_session_seconds == 120.0


def test_hold_mode_is_still_selectable(tmp_path):
    f = tmp_path / "config.yaml"
    f.write_text("voice_activation: hold\n")
    assert load_config(f).voice_activation == "hold"
