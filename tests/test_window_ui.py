"""Window UI state logic, testable without a display or an event loop.

The menu bar was the wrong surface: on a notched MacBook with a busy menu bar,
macOS silently drops overflow status items -- created, isVisible=True, nowhere
to draw, no error to find. A window cannot be hidden that way.

Only the AppKit drawing needs live testing; everything that decides WHAT to
show is plain functions and a class whose window handle stays None until run().
"""
from assistant.ui.window import AssistantWindow, button_text, status_text


class FakeTalker:
    def __init__(self):
        self.is_listening = False
        self.events = []

    def start_listening(self):
        self.is_listening = True
        self.events.append("start")

    def stop_listening(self):
        self.is_listening = False
        self.events.append("stop")

    def shutdown(self):
        self.events.append("shutdown")


def test_every_state_has_readable_text():
    seen = [status_text(s) for s in ("idle", "listening", "thinking", "speaking", "error")]
    assert all(seen) and len(set(seen)) == len(seen)


def test_unknown_state_falls_back():
    assert status_text("nonsense")


def test_button_says_what_the_click_will_do():
    assert button_text(False) == "Start Listening"
    assert button_text(True) == "Stop Listening"


def test_clicking_starts_and_stops():
    talker = FakeTalker()
    win = AssistantWindow(talker)
    win.toggle()
    assert talker.events == ["start"] and win._state == "listening"
    win.toggle()
    assert talker.events == ["start", "stop"] and win._state == "thinking"


def test_voice_events_drive_the_display():
    win = AssistantWindow(FakeTalker())
    win.on_voice_event("transcribed", "what is on my desktop")
    assert win._state == "thinking" and "desktop" in win._last
    win.on_voice_event("answered", "Three files.")
    assert win._state == "idle" and "Three files." in win._last


def test_errors_are_shown_not_hidden():
    win = AssistantWindow(FakeTalker())
    win.on_voice_event("error", RuntimeError("mic died"))
    assert win._state == "error" and "mic died" in win._last


def test_updates_before_run_do_not_touch_appkit():
    """The voice thread may report state before the window exists."""
    win = AssistantWindow(FakeTalker())
    win.set_state("listening")
    win.set_last_exchange("hello")
    assert win._state == "listening"


def test_blank_exchange_shows_a_placeholder():
    win = AssistantWindow(FakeTalker())
    win.set_last_exchange("   ")
    assert win._last.strip()
