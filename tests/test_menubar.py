"""Menu-bar state logic, testable without an event loop or a display.

The AppKit parts cannot be unit-tested meaningfully, so everything that decides
WHAT to show is kept as plain functions and a class whose AppKit handle is None
until run() is called. That way the state machine -- which is where the bugs
would be -- is covered, and only the drawing is left to live testing.
"""
from assistant.ui.menubar import (
    MenuBarApp,
    menu_label_for,
    title_for,
    toggle_label,
)


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


def test_every_state_has_a_distinct_symbol():
    """The symbol IS the whole indicator; two states sharing one is useless."""
    symbols = [title_for(s) for s in ("idle", "listening", "thinking", "speaking")]
    assert len(set(symbols)) == len(symbols)


def test_unknown_state_falls_back_rather_than_crashing():
    assert title_for("nonsense")
    assert menu_label_for("nonsense")


def test_toggle_label_tells_you_what_the_click_will_do():
    assert toggle_label(False) == "Start Listening"
    assert toggle_label(True) == "Stop Listening"


def test_clicking_starts_listening_and_shows_it():
    talker = FakeTalker()
    app = MenuBarApp(talker)
    app.toggle()
    assert talker.events == ["start"]
    assert app._state == "listening"
    assert title_for(app._state) == title_for("listening")


def test_clicking_again_stops():
    talker = FakeTalker()
    app = MenuBarApp(talker)
    app.toggle()
    app.toggle()
    assert talker.events == ["start", "stop"]
    assert app._state == "thinking", "should show it is working on the answer"


def test_voice_events_drive_the_indicator():
    app = MenuBarApp(FakeTalker())
    app.on_voice_event("transcribed", "what is on my desktop")
    assert app._state == "thinking"
    assert "what is on my desktop" in app._last_exchange

    app.on_voice_event("answered", "Three files.")
    assert app._state == "idle"
    assert "Three files." in app._last_exchange


def test_errors_are_visible_in_the_menu_bar():
    app = MenuBarApp(FakeTalker())
    app.on_voice_event("error", RuntimeError("mic died"))
    assert app._state == "error"
    assert "mic died" in app._last_exchange


def test_state_updates_before_run_do_not_touch_appkit():
    """The voice thread may report state before the UI exists."""
    app = MenuBarApp(FakeTalker())
    app.set_state("listening")      # must not raise with no NSStatusItem
    app.set_last_exchange("hello")
    assert app._state == "listening"


def test_empty_exchange_shows_a_placeholder_not_a_blank_row():
    app = MenuBarApp(FakeTalker())
    app.set_last_exchange("   ")
    assert app._last_exchange.strip()
