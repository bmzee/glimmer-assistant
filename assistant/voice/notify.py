"""Make each turn visible, because audio is the only channel the app has.

Packaged, there is no window and no Dock icon. Miss the spoken reply and it is
gone -- no transcript, no scrollback, no replay -- and nothing indicates the
app heard you or is even running.

Notification Centre keeps history, so a missed answer becomes recoverable
without building any UI at all. This is the cheap version of the menu-bar
indicator, not a replacement for it.
"""
from __future__ import annotations

import shutil
import subprocess

_TITLE = "Glimmer Assistant"
_MAX_BODY = 240  # notification panels truncate anyway; do it deliberately


def _trim(text: str) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= _MAX_BODY:
        return text
    return text[: _MAX_BODY - 1].rstrip() + "…"


def notification_for(event: str, payload) -> tuple[str, str] | None:
    """Map a VoiceSession event to (title, body), or None to stay quiet.

    'listening' fires on every key press and is deliberately silent: one
    notification per press would be unusable noise.
    """
    if event == "transcribed":
        return (f"{_TITLE} heard you", _trim(payload))
    if event == "answered":
        return (_TITLE, _trim(payload))
    if event == "error":
        return (f"{_TITLE} error", _trim(payload))
    return None


def _osascript_notify(title: str, body: str) -> None:
    osascript = shutil.which("osascript")
    if not osascript:
        return
    # Quote by escaping: notification text is model output and can contain
    # anything, including quotes that would otherwise break the script.
    safe_body = body.replace("\\", "\\\\").replace('"', '\\"')
    safe_title = title.replace("\\", "\\\\").replace('"', '\\"')
    subprocess.run(
        [osascript, "-e",
         f'display notification "{safe_body}" with title "{safe_title}"'],
        capture_output=True, timeout=30,
    )


class Notifier:
    def __init__(self, send=None):
        self._send = send or _osascript_notify

    def notify(self, event: str, payload) -> None:
        pair = notification_for(event, payload)
        if pair is None:
            return
        try:
            self._send(*pair)
        except Exception:
            # A notification is a nicety. A failed one must never take down a
            # voice turn that otherwise succeeded.
            pass
