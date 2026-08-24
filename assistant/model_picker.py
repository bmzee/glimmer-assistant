"""Choose a model from what Ollama actually has installed.

The packaged app has no window and no terminal, so the only way to change
models was to find and edit a YAML file — which nobody discovers. This asks
Ollama what is pulled, offers exactly those, and remembers the answer.

Only installed models are ever offered. Listing one that is not pulled would
move the failure from selection time (where it is obvious and recoverable) to
first use (where it looks like the app is broken).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import urllib.request
from pathlib import Path

from assistant.config import USER_CONFIG_PATH

_TIMEOUT = 5.0


def _fetch_tags(base_url: str = "http://localhost:11434") -> dict:
    with urllib.request.urlopen(f"{base_url}/api/tags", timeout=_TIMEOUT) as r:
        return json.loads(r.read())


def installed_models(fetch=None) -> list[str]:
    """Model names Ollama reports, sorted. Empty when it cannot be reached."""
    try:
        payload = (fetch or _fetch_tags)()
        names = [m.get("name") for m in payload.get("models", []) if m.get("name")]
    except Exception:
        return []
    return sorted(names)


def _configured_model(config_path: Path) -> str | None:
    """Return the model only if it is ACTIVELY set, not merely mentioned.

    The shipped template lists `# llm_model: nemotron-3.5-lightning:30b-a3b-q4_K_M` as documentation.
    Treating a commented line as a choice would mean never prompting anyone.
    """
    try:
        text = Path(config_path).read_text()
    except OSError:
        return None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if stripped.startswith("llm_model:"):
            value = stripped.split(":", 1)[1].strip()
            return value or None
    return None


def should_prompt(config_path: Path | None = None) -> bool:
    return _configured_model(config_path or USER_CONFIG_PATH) is None


def ask_via_dialog(models: list[str]) -> str | None:
    """Native chooser; an LSUIElement app has no window of its own to draw in."""
    osascript = shutil.which("osascript")
    if not osascript:
        return None
    items = ", ".join(json.dumps(m) for m in models)
    script = (
        f"choose from list {{{items}}} "
        'with title "Glimmer Assistant" '
        'with prompt "Which model should the assistant use?" '
        f"default items {{{json.dumps(models[0])}}}"
    )
    try:
        result = subprocess.run(
            [osascript, "-e", script], capture_output=True, text=True, timeout=300
        )
    except Exception:
        return None
    choice = result.stdout.strip()
    # osascript prints "false" when the user cancels.
    if not choice or choice == "false":
        return None
    return choice


def _persist(config_path: Path, model: str) -> None:
    """Set llm_model, leaving every other setting untouched."""
    path = Path(config_path)
    try:
        text = path.read_text() if path.exists() else ""
    except OSError:
        text = ""

    lines = text.splitlines()
    out, replaced = [], False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("llm_model:") and not stripped.startswith("#"):
            if not replaced:
                out.append(f"llm_model: {model}")
                replaced = True
            continue  # drop any duplicate active entries
        out.append(line)
    if not replaced:
        out.append(f"llm_model: {model}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out).rstrip() + "\n")


def choose_model(
    models: list[str] | None = None,
    ask=None,
    config_path: Path | None = None,
) -> str | None:
    """Offer the installed models and remember the choice.

    Returns the chosen name, or None if the user cancelled or there was
    nothing to offer. A config we cannot write is not fatal: the choice still
    applies to this run.
    """
    models = installed_models() if models is None else models
    if not models:
        # Nothing to choose from. preflight already reports the real problem
        # (Ollama missing, or no model pulled) with a remedy.
        return None

    choice = (ask or ask_via_dialog)(models)
    if not choice or choice not in models:
        return None

    try:
        _persist(config_path or USER_CONFIG_PATH, choice)
    except OSError:
        pass  # unwritable config must not lose the selection for this run
    return choice
