from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Config:
    llm_base_url: str = "http://localhost:11434/v1"
    llm_model: str = "muse-glimmer:30b"
    llm_api_key: str = "ollama"  # Ollama ignores the value but the SDK requires one
    llm_timeout_seconds: float = 120.0
    max_iterations: int = 15
    tool_result_max_chars: int = 16000
    allowed_roots: list[str] = field(default_factory=lambda: ["~"])
    log_path: str = "~/.glimmer-assistant/actions.jsonl"
    voice_stt_model: str = "mlx-community/parakeet-tdt-0.6b-v2"
    voice_tts_voice: str = "af_heart"
    voice_hotkey: str = "ctrl"
    voice_min_utterance_seconds: float = 0.3
    enable_web: bool = True
    enable_apple: bool = True
    enable_m365: bool = False
    m365_client_id: str = ""
    mcp_servers: list = field(default_factory=list)


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
