"""Load the model weights before the user speaks, not during their first command.

Ollama unloads an idle model, and reloading 17-25GB was measured at 16-29s on
this hardware. That cost lands on the first command after the app opens, which
is the one that decides whether the user believes the thing works at all.

Why this is not a one-liner in LLMClient: the app talks to Ollama through its
OpenAI-compatible /v1 shim, and that shim silently DROPS keep_alive. Measured
against a live server:

    plain OpenAI call                          -> expires in 30.0 min (default)
    OpenAI call, extra_body keep_alive='45m'   -> expires in 30.0 min  (dropped)
    native /api/chat,     keep_alive='45m'     -> expires in 45.0 min  (honoured)

So the pin has to bypass the shim and go to the native endpoint.
"""
from __future__ import annotations

import json
import urllib.request

# Long enough to cover a normal working session's idle gaps. Ollama resets the
# timer on every use, so this only has to outlast the pauses between commands.
DEFAULT_KEEP_ALIVE = "2h"


def native_chat_url(base_url: str) -> str:
    """Ollama's native chat endpoint, derived from the configured OpenAI base."""
    root = (base_url or "").rstrip("/")
    if root.endswith("/v1"):
        root = root[: -len("/v1")]
    return f"{root}/api/chat"


def _post(url: str, body: dict) -> None:
    request = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        response.read()


def preload_model(
    base_url: str,
    model: str,
    keep_alive: str = DEFAULT_KEEP_ALIVE,
    post=None,
) -> bool:
    """Pin ``model`` in memory. Returns whether it worked.

    Never raises: a cold cache costs one slow turn, but an exception here would
    cost the whole app. Sends no messages, so Ollama loads the weights and
    returns without generating anything.
    """
    body = {"model": model, "messages": [], "keep_alive": keep_alive, "stream": False}
    try:
        (post or _post)(native_chat_url(base_url), body)
        return True
    except Exception:
        return False
