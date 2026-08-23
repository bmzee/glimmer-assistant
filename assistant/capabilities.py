"""What the assistant can and cannot do right now, and why.

macOS grants permissions one at a time and a denied one is invisible: the
push-to-talk key simply does nothing, a calendar read simply fails. Input
Monitoring is the worst of them — the global hotkey needs it, nobody thinks to
grant it, and without it the app looks completely dead.

The report is capability-first rather than permission-first. A user cares that
"read your email" is unavailable; "Apple Events grant for Mail" is the
implementation detail, useful only as the instruction for fixing it.

Probes are non-destructive: each asks the smallest possible question (count the
calendars, preflight the screen-capture API) rather than doing real work.
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

_TIMEOUT = 15


@dataclass(frozen=True)
class Capability:
    name: str
    granted: bool
    required: bool
    enables: str
    how_to_grant: str


def _osascript_ok(script: str) -> bool:
    """True when the script runs. A TCC denial surfaces as -1743."""
    osascript = shutil.which("osascript")
    if not osascript:
        return False
    result = subprocess.run(
        [osascript, "-e", script], capture_output=True, text=True, timeout=_TIMEOUT
    )
    return result.returncode == 0


def _automation_calendar() -> bool:
    return _osascript_ok('tell application "Calendar" to count calendars')


def _automation_mail() -> bool:
    return _osascript_ok('tell application "Mail" to count accounts')


def _automation_system_events() -> bool:
    return _osascript_ok('tell application "System Events" to count processes')


def _screen_recording() -> bool:
    # CGPreflightScreenCaptureAccess asks without triggering the prompt, which
    # is what a status report wants: reporting state must not change it.
    from Quartz import CGPreflightScreenCaptureAccess

    return bool(CGPreflightScreenCaptureAccess())


def _microphone() -> bool:
    # No AVFoundation binding here, so ask the device layer instead: opening a
    # stream is the same thing the app does, and TCC answers it the same way.
    import sounddevice

    try:
        sounddevice.check_input_settings()
        return True
    except Exception:
        return False


def _input_monitoring() -> bool:
    from Quartz import kAXTrustedCheckOptionPrompt  # noqa: F401
    from ApplicationServices import AXIsProcessTrusted

    return bool(AXIsProcessTrusted())


_DEFAULT_PROBES = {
    "microphone": _microphone,
    "input_monitoring": _input_monitoring,
    "automation_calendar": _automation_calendar,
    "automation_mail": _automation_mail,
    "automation_system_events": _automation_system_events,
    "screen_recording": _screen_recording,
}

_SETTINGS = "System Settings > Privacy & Security"

# required=True means the assistant cannot be spoken to at all without it.
# Everything else costs a category of task, not the whole app.
_SPEC = [
    ("microphone", "Microphone", True,
     "Hearing you at all. Without it the assistant cannot take any spoken request.",
     f"{_SETTINGS} > Microphone — enable Glimmer Assistant."),
    ("input_monitoring", "Input Monitoring", True,
     "The push-to-talk hotkey. Without it the key does nothing and the app "
     "looks dead, even though it is running.",
     f"{_SETTINGS} > Input Monitoring (and Accessibility) — enable Glimmer Assistant."),
    ("automation_mail", "Automation: Mail", False,
     "Reading your recent email and drafting replies.",
     f"{_SETTINGS} > Automation > Glimmer Assistant — enable Mail."),
    ("automation_calendar", "Automation: Calendar", False,
     "Reading your schedule and creating events.",
     f"{_SETTINGS} > Automation > Glimmer Assistant — enable Calendar."),
    ("automation_system_events", "Automation: System Events", False,
     "Listing and focusing windows, and quitting apps.",
     f"{_SETTINGS} > Automation > Glimmer Assistant — enable System Events."),
    ("screen_recording", "Screen Recording", False,
     "Taking screenshots.",
     f"{_SETTINGS} > Screen Recording — enable Glimmer Assistant, then restart it."),
]


def _safe(probe) -> bool:
    """An unknown state must read as unavailable, never as working."""
    try:
        return bool(probe())
    except Exception:
        return False


def capability_report(probes: dict | None = None) -> list[Capability]:
    p = {**_DEFAULT_PROBES, **(probes or {})}
    return [
        Capability(
            name=name,
            granted=_safe(p[key]),
            required=required,
            enables=enables,
            how_to_grant=how,
        )
        for key, name, required, enables, how in _SPEC
    ]


def missing_required(report: list[Capability]) -> list[Capability]:
    return [c for c in report if c.required and not c.granted]


def format_report(report: list[Capability]) -> str:
    granted = [c for c in report if c.granted]
    denied = [c for c in report if not c.granted]

    lines: list[str] = []
    if granted:
        lines.append("Available now:")
        lines += [f"  ✓ {c.name} — {c.enables}" for c in granted]
    if denied:
        if lines:
            lines.append("")
        lines.append("Unavailable until you grant permission:")
        for c in denied:
            tag = "  ✗" if c.required else "  ○"
            need = " (required)" if c.required else ""
            lines.append(f"{tag} {c.name}{need} — {c.enables}")
            lines.append(f"      {c.how_to_grant}")
    return "\n".join(lines)
