"""Show what the app can and cannot do, and which permission unlocks each.

macOS grants permissions one at a time, and a denied one is invisible: the
push-to-talk key just does nothing, calendar reads just fail. Worse, Input
Monitoring is required for the global hotkey and is not something anyone thinks
to grant -- the app looks completely dead without it.

So the report is capability-first, not permission-first: the user cares that
"read your email" is unavailable, not that an Apple Events grant is missing.
Every probe is injected; these tests never touch real TCC.
"""
from assistant.capabilities import (
    Capability,
    capability_report,
    format_report,
    missing_required,
)


def _probes(**overrides):
    base = {
        "microphone": lambda: True,
        "input_monitoring": lambda: True,
        "automation_calendar": lambda: True,
        "automation_mail": lambda: True,
        "automation_system_events": lambda: True,
        "screen_recording": lambda: True,
    }
    base.update(overrides)
    return base


def test_all_granted_reports_everything_available():
    report = capability_report(probes=_probes())
    assert all(c.granted for c in report)
    assert missing_required(report) == []


def test_each_capability_says_what_it_enables():
    for cap in capability_report(probes=_probes()):
        assert cap.enables, f"{cap.name} does not say what it is for"
        assert cap.how_to_grant, f"{cap.name} does not say how to grant it"


def test_input_monitoring_is_reported_because_ptt_dies_silently_without_it():
    report = capability_report(probes=_probes(input_monitoring=lambda: False))
    denied = [c for c in report if not c.granted]
    assert any("input monitoring" in c.name.lower() for c in denied)
    ptt = next(c for c in denied if "input monitoring" in c.name.lower())
    assert "push-to-talk" in ptt.enables.lower() or "hotkey" in ptt.enables.lower()


def test_microphone_and_hotkey_are_required_not_optional():
    """Without either, the assistant cannot be spoken to at all."""
    report = capability_report(
        probes=_probes(microphone=lambda: False, input_monitoring=lambda: False)
    )
    names = [c.name.lower() for c in missing_required(report)]
    assert any("microphone" in n for n in names)
    assert any("input monitoring" in n for n in names)


def test_calendar_denied_is_optional_not_a_blocker():
    """The assistant still works; it just cannot do calendar tasks."""
    report = capability_report(probes=_probes(automation_calendar=lambda: False))
    cal = next(c for c in report if "calendar" in c.name.lower())
    assert not cal.granted
    assert not cal.required
    assert missing_required(report) == []


def test_report_lists_granted_and_denied_separately():
    text = format_report(
        capability_report(probes=_probes(screen_recording=lambda: False))
    )
    assert "Screen Recording" in text
    lower = text.lower()
    assert "available" in lower or "granted" in lower
    assert "unavailable" in lower or "not granted" in lower or "missing" in lower


def test_report_names_the_task_lost_not_just_the_permission():
    text = format_report(
        capability_report(probes=_probes(automation_mail=lambda: False))
    )
    assert "mail" in text.lower()
    assert any(w in text.lower() for w in ("email", "e-mail", "messages"))


def test_a_probe_that_raises_is_reported_as_not_granted():
    """An unknown state must read as unavailable, never as working."""

    def boom():
        raise OSError("tcc unavailable")

    report = capability_report(probes=_probes(screen_recording=boom))
    cap = next(c for c in report if "screen" in c.name.lower())
    assert not cap.granted


def test_capability_is_immutable():
    c = Capability(
        name="x", granted=True, required=True, enables="e", how_to_grant="h"
    )
    try:
        c.granted = False
    except Exception:
        return
    raise AssertionError("Capability should be frozen")
