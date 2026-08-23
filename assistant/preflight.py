"""Startup checks that explain themselves, because a bundled app cannot print.

Launched from the .app there is no terminal, and `LSUIElement` means no Dock
icon either, so every `print()` in main.py goes nowhere. A missing Ollama, an
unpulled model and an undownloaded voice model all look identical to the user:
the app appears to do nothing at all.

Each check therefore carries a *remedy* — the concrete thing the user should
do — so the launcher can put it in a dialog. Blocking problems stop startup;
warnings (a voice model that will download itself, just slowly) do not.
"""
from __future__ import annotations

import json
import shutil
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from assistant.config import Config

_OLLAMA_TIMEOUT = 3.0


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str
    remedy: str
    blocking: bool


def _ollama_reachable(base_url: str = "http://localhost:11434") -> bool:
    try:
        with urllib.request.urlopen(f"{base_url}/api/tags", timeout=_OLLAMA_TIMEOUT):
            return True
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def _model_present(name: str, base_url: str = "http://localhost:11434") -> bool:
    try:
        with urllib.request.urlopen(f"{base_url}/api/tags", timeout=_OLLAMA_TIMEOUT) as r:
            tags = json.loads(r.read()).get("models", [])
    except Exception:
        return False
    # Ollama reports "name:tag"; a bare name should still match its default tag.
    wanted = name if ":" in name else f"{name}:latest"
    return any(m.get("name") in (name, wanted) for m in tags)


def _voice_models_present() -> bool:
    cache = Path("~/.cache/glimmer-assistant/kokoro").expanduser()
    return cache.is_dir() and any(cache.glob("*.onnx"))


def _chromium_present() -> bool:
    cache = Path("~/Library/Caches/ms-playwright").expanduser()
    return cache.is_dir() and any(cache.glob("chromium-*"))


_DEFAULT_PROBES = {
    "ollama_reachable": _ollama_reachable,
    "model_present": _model_present,
    "voice_models_present": _voice_models_present,
    "chromium_present": _chromium_present,
}


def _safe(probe, *args) -> bool:
    """A probe that raises must not take the app down before it starts."""
    try:
        return bool(probe(*args))
    except Exception:
        return False


def run_preflight(cfg: Config, probes: dict | None = None) -> list[Check]:
    p = {**_DEFAULT_PROBES, **(probes or {})}
    checks: list[Check] = []

    ollama_up = _safe(p["ollama_reachable"])
    checks.append(
        Check(
            name="Ollama running",
            ok=ollama_up,
            detail="reachable at localhost:11434" if ollama_up
            else "no response from localhost:11434",
            remedy="" if ollama_up else (
                "Install Ollama from https://ollama.com and open it. "
                "Glimmer Assistant runs its model through Ollama and cannot "
                "start without it."
            ),
            blocking=True,
        )
    )

    # Only ask about the model if Ollama answered. Reporting "model missing"
    # when the server is down is two errors for one cause, and sends the user
    # to fix the wrong thing.
    if ollama_up:
        has_model = _safe(p["model_present"], cfg.llm_model)
        checks.append(
            Check(
                name="Model available",
                ok=has_model,
                detail=f"{cfg.llm_model} "
                + ("is pulled" if has_model else "is not pulled"),
                remedy="" if has_model else f"Run: ollama pull {cfg.llm_model}",
                blocking=True,
            )
        )

    voice_ok = _safe(p["voice_models_present"])
    checks.append(
        Check(
            name="Voice models",
            ok=voice_ok,
            detail="downloaded" if voice_ok else "not downloaded yet",
            remedy="" if voice_ok else (
                "They download automatically on first use (about 1 GB). "
                "The first spoken reply will be slow."
            ),
            blocking=False,
        )
    )

    if cfg.enable_web:
        chromium_ok = _safe(p["chromium_present"])
        checks.append(
            Check(
                name="Browser (Chromium)",
                ok=chromium_ok,
                detail="installed" if chromium_ok else "not installed",
                remedy="" if chromium_ok else (
                    "Run: playwright install chromium — until then, web "
                    "browsing requests will fail."
                ),
                blocking=False,
            )
        )

    return checks


def format_problems(checks: list[Check]) -> str:
    """Render failures as user-facing text. Empty string when all is well."""
    bad = [c for c in checks if not c.ok]
    if not bad:
        return ""
    lines = []
    for c in bad:
        label = "" if c.blocking else " (optional)"
        lines.append(f"• {c.name}{label}: {c.detail}")
        if c.remedy:
            lines.append(f"    {c.remedy}")
    return "\n".join(lines)


def blocking_problems(checks: list[Check]) -> list[Check]:
    return [c for c in checks if not c.ok and c.blocking]


def show_dialog(title: str, message: str) -> None:
    """Surface a message with no terminal available.

    Uses osascript rather than a GUI toolkit: it is already a dependency of the
    Apple tools, adds nothing to the bundle, and works from an LSUIElement app.
    """
    script = (
        f'display dialog {json.dumps(message)} with title {json.dumps(title)} '
        'buttons {"OK"} default button "OK" with icon caution'
    )
    osascript = shutil.which("osascript")
    if not osascript:
        return
    try:
        import subprocess

        subprocess.run([osascript, "-e", script], capture_output=True, timeout=120)
    except Exception:
        pass  # a failed dialog must never be the reason startup dies
