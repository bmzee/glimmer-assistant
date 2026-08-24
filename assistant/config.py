from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Config:
    llm_base_url: str = "http://localhost:11434/v1"
    # Default chosen by the three-way race in docs/model-ab.md. All three
    # installed models score 10/10, so accuracy does not decide -- speed does.
    # Nemotron is a mixture-of-experts (32.9B total, ~3B ACTIVE per token)
    # against Qwen's dense 27B, so it decodes at 86.8 tok/s vs 14.8, and the
    # full eval suite runs in 155.9s vs 285.1s. For the user that is a ~5s
    # wait instead of ~20s. Set to "qwen3.8:27b" or "muse-glimmer:30b-mlx"
    # to switch back; both are equally correct, just slower.
    llm_model: str = "nemotron-3.5-lightning:30b-a3b-q4_K_M"
    llm_api_key: str = "ollama"  # Ollama ignores the value but the SDK requires one
    llm_timeout_seconds: float = 120.0
    # Reasoning models emit hidden thinking tokens before their first visible
    # token. "none" suppresses that (7.5x faster to first token) but MEASURED
    # WORSE: eval drops 10/10 -> 9/10 (fails on tool use) and a literal
    # "</think>" leaks into visible text ~1 turn in 10, which the voice path
    # would speak aloud. Do not enable for voice. Empty means the key is
    # omitted entirely, so endpoints that reject it keep working. docs/latency.md
    llm_reasoning_effort: str = ""
    max_iterations: int = 15
    tool_result_max_chars: int = 16000
    allowed_roots: list[str] = field(default_factory=lambda: ["~"])
    log_path: str = "~/.glimmer-assistant/actions.jsonl"
    voice_stt_model: str = "mlx-community/parakeet-tdt-0.6b-v2"
    voice_tts_voice: str = "af_heart"
    # Right Option. "ctrl" was the original default and was a poor one: it is a
    # modifier pressed constantly for ordinary shortcuts, so Ctrl-C would open a
    # voice turn. alt_r is the only good candidate that survives the real
    # constraints -- fn is not exposed by pynput at all, ctrl_r and F13-F16 do
    # not exist on MacBook keyboards, and caps_lock toggles state and has an
    # activation delay. See docs/voice-hotkey.md.
    voice_hotkey: str = "alt_r"
    voice_min_utterance_seconds: float = 0.3
    # "listen": hands-free. The microphone stays open and an utterance is
    #   bounded by speech itself -- start talking and it hears you, stop and it
    #   answers. The DEFAULT: no clicking, and no permission beyond Microphone.
    # "click": start/stop from a button. Needs no permission either, but
    #   click-speak-click is worse than just talking.
    # "double_tap": tap the hotkey twice to start, twice again to stop.
    # "hold": classic push-to-talk, hold the key while speaking.
    voice_activation: str = "listen"
    voice_tap_window_seconds: float = 0.4
    # A toggle can be left on in a way push-to-talk cannot, so a forgotten
    # session stops itself rather than recording indefinitely.
    voice_max_session_seconds: float = 120.0
    # Hands-free tuning. speech_level is the RMS above which a frame counts as
    # speech; silence_seconds is how long a pause must run before the utterance
    # is considered finished -- too short truncates anyone who thinks mid
    # sentence, too long makes every reply feel laggy.
    # Speak a short filler as soon as the transcript lands. It does not make
    # the answer faster; it stops a 15-24s gap reading as a broken app.
    voice_acknowledge: bool = True
    voice_speech_level: float = 0.06
    voice_silence_seconds: float = 0.9
    enable_web: bool = True
    enable_apple: bool = True
    enable_m365: bool = False
    m365_client_id: str = ""
    mcp_servers: list = field(default_factory=list)
    context_max_tokens: int = 131072
    compact_threshold: float = 0.65


def load_config(path: str | Path | None = None) -> Config:
    cfg = Config()
    if path is None:
        return cfg
    data = yaml.safe_load(Path(path).read_text()) or {}
    for key, value in data.items():
        if hasattr(cfg, key):
            setattr(cfg, key, value)
    _normalize_allowed_roots(cfg)
    return cfg


def _normalize_allowed_roots(cfg: Config) -> None:
    value = cfg.allowed_roots
    if isinstance(value, str):
        cfg.allowed_roots = [value]
    elif isinstance(value, list) and all(isinstance(v, str) for v in value):
        pass
    else:
        raise ValueError(
            f"config key 'allowed_roots' must be a string or a list of strings, got {value!r}"
        )


# A packaged .app cannot use a config inside itself: the file is not shipped
# there, editing anything inside a code-signed bundle invalidates the signature
# (and with it the TCC grants), and an app update would replace it. So the
# user-editable config lives beside the audit log instead.
USER_CONFIG_PATH = Path("~/.glimmer-assistant/config.yaml").expanduser()

PACKAGED_CONFIG_PATH = Path(__file__).parent / "config.yaml"

_TEMPLATE = """\
# Glimmer Assistant configuration.
# Everything here is commented out and shows the built-in default.
# Uncomment a line to change it, then restart the app.

# The Ollama model to use. It must already be pulled:  ollama pull <name>
# llm_model: nemotron-3.5-lightning:30b-a3b-q4_K_M
# llm_model: qwen3.8:27b           # also 10/10, but ~6x slower per token
# llm_model: muse-glimmer:30b-mlx  # also 10/10, slowest of the three overall

# llm_base_url: http://localhost:11434/v1

# Directories the assistant may read and write. Everything else is refused.
# allowed_roots: ["~"]

# Optional tool groups.
# enable_web: true
# enable_apple: true
# enable_m365: false
# m365_client_id: ""

# Push-to-talk key, and the shortest utterance treated as speech.
# voice_hotkey: alt_r        # right Option; see docs/voice-hotkey.md for alternatives
# voice_activation: listen       # 'click' for a button; 'double_tap'/'hold'
#                                # use the hotkey,
#                                # which needs Input Monitoring granted
# voice_tap_window_seconds: 0.4
# voice_max_session_seconds: 120.0
# voice_min_utterance_seconds: 0.3

# Suppresses the model's hidden reasoning tokens. Faster to first word, but
# MEASURED WORSE: eval drops 10/10 -> 9/10 and reasoning markers can leak into
# spoken output. See docs/latency.md before enabling.
# llm_reasoning_effort: none
"""


def resolve_config_path(
    user: str | Path | None = None,
    packaged: str | Path | None = None,
) -> Path | None:
    """User config first, then the one beside the module, then defaults."""
    user_path = Path(user) if user is not None else USER_CONFIG_PATH
    packaged_path = Path(packaged) if packaged is not None else PACKAGED_CONFIG_PATH
    if user_path.is_file():
        return user_path
    if packaged_path.is_file():
        return packaged_path
    return None


def ensure_user_config(path: str | Path | None = None) -> bool:
    """Write a commented template so the settings are discoverable at all.

    Returns True only when a file was created. An existing config is never
    touched -- overwriting someone's edited settings on startup would be worse
    than shipping no template. A location we cannot write (read-only home, or
    a file where a directory should be) is not fatal: the app runs on defaults.
    """
    target = Path(path) if path is not None else USER_CONFIG_PATH
    try:
        if target.exists():
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_TEMPLATE)
        return True
    except OSError:
        return False
