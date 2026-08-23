"""A menu-bar item: click to start listening, click to stop.

Two problems this solves at once.

The hotkey needs Input Monitoring, which macOS gates and which — ungranted —
makes the app appear completely dead. A click in our own UI needs no permission.

And the app had no visible state at all: no window, no Dock icon, no indication
it was running, had heard you, or was thinking. The title carries that state, so
"is it listening?" stops being a guess.

Deliberately a menu-bar item rather than a window: the app is already
LSUIElement, and a background assistant that steals a window on launch is worse
than one that waits quietly in the menu bar.
"""
from __future__ import annotations

import threading

# State -> what the menu bar shows. Symbols read at a glance; the words are for
# the menu, where there is room.
STATES = {
    "idle": ("●", "Ready"),
    "listening": ("◉", "Listening…"),
    "thinking": ("◐", "Thinking…"),
    "speaking": ("◑", "Speaking…"),
    "error": ("✕", "Error"),
}


def title_for(state: str, listening: bool = False) -> str:
    symbol, _ = STATES.get(state, STATES["idle"])
    return symbol


def menu_label_for(state: str) -> str:
    _, label = STATES.get(state, STATES["idle"])
    return label


def toggle_label(listening: bool) -> str:
    return "Stop Listening" if listening else "Start Listening"


class MenuBarApp:
    """Owns the NSStatusItem and drives a ClickToTalk.

    AppKit is imported lazily so the module can be imported (and its pure
    helpers tested) on a machine with no display and in a test run that must
    not start an event loop.
    """

    def __init__(self, talker, on_quit=None, session_runner=None):
        self._talker = talker
        self._on_quit = on_quit
        self._session_runner = session_runner
        self._state = "idle"
        self._last_exchange = "No requests yet"
        self._item = None
        self._menu = None

    # -- state, called from the voice thread ------------------------------
    def set_state(self, state: str) -> None:
        self._state = state
        self._refresh()

    def set_last_exchange(self, text: str) -> None:
        self._last_exchange = (text or "").strip() or "No requests yet"
        self._refresh()

    def on_voice_event(self, name, payload) -> None:
        """Bridge VoiceSession events onto the menu bar."""
        if name == "transcribed":
            self.set_state("thinking")
            self.set_last_exchange(f"You: {payload}")
        elif name == "answered":
            self.set_state("idle")
            self.set_last_exchange(f"Reply: {payload}")
        elif name == "error":
            self.set_state("error")
            self.set_last_exchange(f"Error: {payload}")

    # -- AppKit -----------------------------------------------------------
    def _refresh(self) -> None:
        if self._item is None:
            return
        try:
            from AppKit import NSAttributedString  # noqa: F401

            self._item.button().setTitle_(title_for(self._state))
            self._rebuild_menu()
        except Exception:
            pass  # a UI refresh must never take down a voice turn

    def _rebuild_menu(self) -> None:
        from AppKit import NSMenu, NSMenuItem

        menu = NSMenu.alloc().init()

        status = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            menu_label_for(self._state), None, ""
        )
        status.setEnabled_(False)
        menu.addItem_(status)

        exchange = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            self._last_exchange[:120], None, ""
        )
        exchange.setEnabled_(False)
        menu.addItem_(exchange)

        menu.addItem_(NSMenuItem.separatorItem())

        toggle = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            toggle_label(self._talker.is_listening), "toggle:", ""
        )
        toggle.setTarget_(self._handler)
        menu.addItem_(toggle)

        menu.addItem_(NSMenuItem.separatorItem())
        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit Glimmer Assistant", "quit:", "q"
        )
        quit_item.setTarget_(self._handler)
        menu.addItem_(quit_item)

        self._item.setMenu_(menu)
        self._menu = menu

    def toggle(self) -> None:
        if self._talker.is_listening:
            self._talker.stop_listening()
            self.set_state("thinking")
        else:
            self._talker.start_listening()
            self.set_state("listening")

    def run(self) -> None:
        """Start the AppKit event loop. Blocks; the voice session runs behind."""
        import objc
        from AppKit import NSApplication, NSStatusBar, NSVariableStatusItemLength
        from Foundation import NSObject

        app = NSApplication.sharedApplication()

        outer = self

        class _Handler(NSObject):
            def toggle_(self, _sender):
                outer.toggle()

            def quit_(self, _sender):
                outer._talker.shutdown()
                if outer._on_quit:
                    outer._on_quit()
                NSApplication.sharedApplication().terminate_(None)

        self._handler = _Handler.alloc().init()
        self._item = NSStatusBar.systemStatusBar().statusItemWithLength_(
            NSVariableStatusItemLength
        )
        self._item.button().setTitle_(title_for(self._state))
        self._rebuild_menu()

        if self._session_runner is not None:
            threading.Thread(target=self._session_runner, daemon=True).start()

        app.run()
