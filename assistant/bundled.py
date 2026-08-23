"""Entry point for the packaged .app, where nothing can be printed.

Running from a bundle there is no terminal and, with LSUIElement set, no Dock
icon. stdout goes nowhere, so the three ways startup normally communicates --
progress prints, a traceback, a KeyboardInterrupt -- are all invisible. The
app just appears to do nothing.

This wraps the session so that:
  - blocking preflight problems become a dialog and stop startup
  - a crash becomes a dialog instead of a silent disappearance
  - everything, including tracebacks, lands in a log file for diagnosis
"""
from __future__ import annotations

import contextlib
import sys
import traceback
from pathlib import Path

from assistant.config import Config
from assistant.capabilities import (
    capability_report,
    format_report,
    missing_required,
)
from assistant.preflight import (
    blocking_problems,
    format_problems,
    run_preflight,
    show_dialog,
)

DEFAULT_LOG = Path("~/.glimmer-assistant/app.log").expanduser()
_TITLE = "Glimmer Assistant"


@contextlib.contextmanager
def _tee_to(log_path: Path | None):
    """Send stdout/stderr to a log file; a bundle has nowhere else to put them."""
    if log_path is None:
        yield
        return
    log_path = Path(log_path).expanduser()
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handle = log_path.open("a", buffering=1)
    except OSError:
        yield  # a log we cannot open must not stop the app
        return
    saved_out, saved_err = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = handle
    try:
        yield
    finally:
        sys.stdout, sys.stderr = saved_out, saved_err
        handle.close()


def bundled_main(
    cfg: Config,
    *,
    checks=None,
    show=show_dialog,
    run=None,
    log_path: Path | None = None,
    capabilities=None,
) -> int:
    with _tee_to(log_path):
        checks = checks if checks is not None else run_preflight(cfg)
        problems = format_problems(checks)
        if problems:
            print(f"preflight problems:\n{problems}")

        if blocking_problems(checks):
            show(
                f"{_TITLE} can't start",
                "Glimmer Assistant needs the following before it can run:\n\n"
                + problems,
            )
            return 1

        # Permissions are the other half of "why is nothing happening?".
        # A denied grant is invisible: the hotkey just does nothing, a calendar
        # read just fails. Report capability-first -- the user cares that
        # "read your email" is unavailable, not which TCC grant is missing.
        caps = (capabilities if capabilities is not None
                else capability_report(activation=cfg.voice_activation))
        print("capabilities:\n" + format_report(caps))
        blocked = missing_required(caps)
        if blocked:
            show(
                f"{_TITLE} needs permission",
                "Glimmer Assistant is running but cannot hear you yet:\n\n"
                + format_report(caps),
            )

        if run is None:
            from assistant.main import build_voice_session

            session = build_voice_session(cfg, sys.platform)

            # With click activation the menu bar owns the main thread (AppKit
            # requires it) and the voice session runs behind it. That is also
            # what makes the app visible at all: without it there is no window,
            # no Dock icon, and no sign it is running.
            if cfg.voice_activation == "click":
                from assistant.ui.menubar import MenuBarApp

                menubar = MenuBarApp(
                    session.ptt, session_runner=session.run_forever
                )
                session.add_listener(menubar.on_voice_event)
                run = menubar.run
            else:
                run = session.run_forever

        try:
            run()
        except KeyboardInterrupt:
            return 0
        except Exception as e:
            detail = traceback.format_exc()
            print(detail)
            where = log_path or DEFAULT_LOG
            show(
                f"{_TITLE} stopped",
                f"Glimmer Assistant hit an error and stopped:\n\n{e}\n\n"
                f"Details were written to:\n{where}",
            )
            return 1
    return 0


def main() -> int:
    from assistant.config import ensure_user_config, load_config, resolve_config_path
    from assistant.model_picker import choose_model, should_prompt

    # Drop a commented template on first run so the settings are discoverable.
    # Without it a packaged user has no way to know the model is configurable.
    ensure_user_config()

    # First run only: offer the models Ollama actually has. Editing YAML is not
    # a discoverable interface for an app with no window, and the built-in
    # default is only right by accident on someone else's machine.
    if should_prompt():
        choose_model()

    cfg = load_config(resolve_config_path())
    return bundled_main(cfg, log_path=DEFAULT_LOG)


if __name__ == "__main__":
    raise SystemExit(main())
