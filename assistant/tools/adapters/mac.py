from __future__ import annotations

import subprocess

from assistant.tools.adapters.base import PlatformAdapter

# AppleScript string literals are the same injection surface as in apple.py:
# an app name is model-supplied and lands inside a quoted literal.
_TIMEOUT = 30


def _esc(value: str) -> str:
    """Escape for an AppleScript double-quoted literal. Backslash FIRST."""
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def _run(argv: list[str], ok: str, fail: str) -> str:
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, timeout=_TIMEOUT
        )
    except subprocess.TimeoutExpired:
        return f"ERROR: {fail} timed out after {_TIMEOUT}s"
    except (OSError, ValueError) as e:
        return f"ERROR: {e}"
    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "could not create image" in stderr.lower():
            return (
                "ERROR: macOS denied screen capture. Grant this app Screen "
                "Recording permission under System Settings > Privacy & "
                "Security > Screen Recording, then retry."
            )
        if "-1743" in stderr or "not allowed" in stderr.lower():
            return (
                "ERROR: macOS denied Apple Events access. Grant this app control "
                "of the target application under System Settings > Privacy & "
                "Security > Automation, then retry."
            )
        return f"ERROR: {stderr or fail}"
    return result.stdout.strip() or ok


def _osascript(script: str, ok: str, fail: str) -> str:
    return _run(["osascript", "-e", script], ok, fail)


class MacAdapter(PlatformAdapter):
    def launch_app(self, name: str) -> str:
        return _run(["open", "-a", name], f"launched {name}", f"could not open app {name}")

    def open_path(self, path: str) -> str:
        return _run(["open", path], f"opened {path}", f"could not open {path}")

    def quit_app(self, name: str) -> str:
        # `quit` lets the app run its own save prompt rather than killing it,
        # so unsaved work is protected by the app itself.
        return _osascript(
            f'tell application "{_esc(name)}" to quit',
            f"quit {name}",
            f"could not quit {name}",
        )

    # Two live-found failures shaped this script:
    #   -1700 "can't make 0 into type specifier" -- the whole-list coercion
    #         form breaks as soon as a visible process has no front window.
    #   -1719 "invalid index" -- iterating `every application process whose
    #         ...` re-queries the live collection, so it shifts mid-loop.
    # Snapshotting the names to plain strings first avoids both.
    _LIST_WINDOWS = """tell application "System Events"
  set procNames to name of (every application process whose visible is true)
  set out to {}
  repeat with n in procNames
    set pname to n as text
    try
      set end of out to pname & " - " & ¬
        (name of front window of application process pname)
    on error
      set end of out to pname & " - (no window)"
    end try
  end repeat
  set AppleScript's text item delimiters to linefeed
  return out as text
end tell"""

    def list_windows(self) -> str:
        return _osascript(
            self._LIST_WINDOWS, "no visible windows", "could not list windows"
        )

    def focus_window(self, name: str) -> str:
        return _osascript(
            f'tell application "{_esc(name)}" to activate',
            f"focused {name}",
            f"could not focus {name}",
        )

    def set_volume(self, level: int) -> str:
        return _osascript(
            f"set volume output volume {int(level)}",
            f"volume set to {level}",
            "could not set volume",
        )

    def screenshot(self, path: str) -> str:
        # -x suppresses the capture sound; the path is allowlisted by the caller.
        return _run(
            ["screencapture", "-x", path],
            f"screenshot saved to {path}",
            "could not capture screen",
        )
