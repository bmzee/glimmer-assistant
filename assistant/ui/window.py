"""A small always-visible window with a Start/Stop button.

The menu bar was the wrong surface. On a MacBook Pro with a notch and a busy
menu bar, macOS silently drops overflow status items: the item is created,
reports isVisible=True, and has nowhere to draw. No error, nothing to debug,
and the app looks dead -- the exact failure the UI was added to prevent.

A window cannot be hidden that way. It is also literally what was asked for: a
minimal interface with a button that starts and stops the assistant.
"""
from __future__ import annotations

import threading

STATE_TEXT = {
    "idle": "Ready",
    "listening": "Listening…",
    "thinking": "Thinking…",
    "speaking": "Speaking…",
    "error": "Error",
}


def status_text(state: str) -> str:
    return STATE_TEXT.get(state, STATE_TEXT["idle"])


def button_text(listening: bool) -> str:
    return "Stop Listening" if listening else "Start Listening"


class AssistantWindow:
    """Owns a small NSWindow driving a ClickToTalk.

    AppKit is imported lazily so the pure helpers stay testable with no display
    and no event loop.
    """

    def __init__(self, talker, on_quit=None, session_runner=None):
        self._talker = talker
        self._on_quit = on_quit
        self._session_runner = session_runner
        self._state = "idle"
        self._last = "Click Start Listening, then speak."
        self._window = None
        self._button = None
        self._status = None
        self._transcript = None

    def set_state(self, state: str) -> None:
        self._state = state
        self._refresh()

    def set_last_exchange(self, text: str) -> None:
        self._last = (text or "").strip() or "No requests yet"
        self._refresh()

    def on_voice_event(self, name, payload) -> None:
        if name == "transcribed":
            self.set_state("thinking")
            self.set_last_exchange(f"You: {payload}")
        elif name == "answered":
            self.set_state("idle")
            self.set_last_exchange(f"Reply: {payload}")
        elif name == "error":
            self.set_state("error")
            self.set_last_exchange(f"Error: {payload}")

    def toggle(self) -> None:
        if self._talker.is_listening:
            self._talker.stop_listening()
            self.set_state("thinking")
        else:
            self._talker.start_listening()
            self.set_state("listening")

    def _refresh(self) -> None:
        if self._window is None:
            return
        try:
            self._status.setStringValue_(status_text(self._state))
            self._transcript.setStringValue_(self._last[:300])
            self._button.setTitle_(button_text(self._talker.is_listening))
        except Exception:
            pass  # a UI refresh must never take down a voice turn

    def run(self) -> None:
        from AppKit import (
            NSApplication,
            NSApplicationActivationPolicyRegular,
            NSBackingStoreBuffered,
            NSButton,
            NSColor,
            NSFont,
            NSMakeRect,
            NSTextField,
            NSTitledWindowMask,
            NSWindow,
            NSWindowStyleMaskClosable,
            NSWindowStyleMaskMiniaturizable,
        )
        from Foundation import NSObject

        app = NSApplication.sharedApplication()
        # Regular, not Accessory: the window must be visible and focusable, and
        # the app needs a Dock icon so it can be found and quit like any app.
        app.setActivationPolicy_(NSApplicationActivationPolicyRegular)

        outer = self

        class _Handler(NSObject):
            def toggle_(self, _sender):
                outer.toggle()

        self._handler = _Handler.alloc().init()

        style = (NSTitledWindowMask | NSWindowStyleMaskClosable
                 | NSWindowStyleMaskMiniaturizable)
        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 380, 170), style, NSBackingStoreBuffered, False
        )
        win.setTitle_("Glimmer Assistant")
        win.center()

        status = NSTextField.alloc().initWithFrame_(NSMakeRect(20, 120, 340, 24))
        status.setEditable_(False)
        status.setBezeled_(False)
        status.setDrawsBackground_(False)
        status.setFont_(NSFont.boldSystemFontOfSize_(16))
        status.setStringValue_(status_text(self._state))

        transcript = NSTextField.alloc().initWithFrame_(NSMakeRect(20, 55, 340, 60))
        transcript.setEditable_(False)
        transcript.setBezeled_(False)
        transcript.setDrawsBackground_(False)
        transcript.setFont_(NSFont.systemFontOfSize_(12))
        transcript.setTextColor_(NSColor.secondaryLabelColor())
        transcript.setStringValue_(self._last)

        button = NSButton.alloc().initWithFrame_(NSMakeRect(20, 15, 340, 32))
        button.setTitle_(button_text(False))
        button.setBezelStyle_(1)
        button.setTarget_(self._handler)
        button.setAction_("toggle:")

        view = win.contentView()
        view.addSubview_(status)
        view.addSubview_(transcript)
        view.addSubview_(button)

        self._window, self._status = win, status
        self._transcript, self._button = transcript, button

        win.makeKeyAndOrderFront_(None)
        app.activateIgnoringOtherApps_(True)

        if self._session_runner is not None:
            threading.Thread(target=self._session_runner, daemon=True).start()

        app.run()
