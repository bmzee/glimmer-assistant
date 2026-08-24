from pathlib import Path

import pytest

from assistant.config import Config, load_config


def test_defaults_without_file():
    cfg = load_config(None)
    assert cfg.llm_base_url == "http://localhost:11434/v1"
    # Default selected by the three-way race in docs/model-ab.md. All three
    # installed models score 10/10, so speed decides: Nemotron is a 3B-active
    # MoE and decodes at 86.8 tok/s against Qwen's 14.8, which is the
    # difference between a 5s and a 20s wait for the user.
    assert cfg.llm_model == "nemotron-3.5-lightning:30b-a3b-q4_K_M"
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


def test_voice_activation_defaults_to_hands_free():
    """Just talk. No key, no button, no permission beyond Microphone.

    The hotkey modes need Input Monitoring, which macOS would not grant; click
    mode needed no permission but click-speak-click is worse than simply
    speaking.
    """
    cfg = load_config(None)
    assert cfg.voice_activation == "listen"
    assert 0 < cfg.voice_speech_level < 1
    assert cfg.voice_silence_seconds > 0
    assert cfg.voice_tap_window_seconds == 0.4
    # A toggle can be left on in a way push-to-talk cannot; it must self-stop.
    assert cfg.voice_max_session_seconds == 120.0


def test_hold_mode_is_still_selectable(tmp_path):
    f = tmp_path / "config.yaml"
    f.write_text("voice_activation: hold\n")
    assert load_config(f).voice_activation == "hold"
