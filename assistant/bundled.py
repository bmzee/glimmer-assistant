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
from assistant.llm.preload import preload_model
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
    preload=preload_model,
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

        # Load the weights now, while the user is still opening the app. Cold,
        # the first command pays a 16-29s reload of a 17-25GB model -- and that
        # is the command that decides whether they think this works at all.
        try:
            preload(cfg.llm_base_url, cfg.llm_model)
        except Exception as e:  # never trade the whole app for a warm cache
            print(f"model preload skipped: {e}")

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

            if cfg.voice_activation in ("listen", "click"):
                # A window, not a menu-bar item: overflow status items are
                # dropped silently on a notched Mac with a busy menu bar, and
                # an invisible control is the failure this UI exists to remove.
                from assistant.ui.window import AssistantWindow

                # Capture objects are cheap and model-free, so the window can
                # exist immediately -- before the 10-30s model load.
                hands_free = cfg.voice_activation == "listen"
                if hands_free:
                    from assistant.voice.vad import VoiceActivityCapture

                    talker = VoiceActivityCapture(
                        min_seconds=cfg.voice_min_utterance_seconds,
                        speech_level=cfg.voice_speech_level,
                        silence_seconds=cfg.voice_silence_seconds,
                    )
                else:
                    from assistant.voice.click import ClickToTalk

                    talker = ClickToTalk(
                        min_seconds=cfg.voice_min_utterance_seconds,
                        max_seconds=cfg.voice_max_session_seconds,
                    )
                ui = AssistantWindow(talker, hands_free=hands_free)

                def build_and_run():
                    """Build the models IN the thread that will use them.

                    MLX streams are thread-local. Building Parakeet on the main
                    thread and running the session on a worker produced
                    'There is no Stream(cpu, 1) in current thread.' on the first
                    transcription -- every turn failed. AppKit owns the main
                    thread, so the models must come to the worker rather than
                    the other way round.

                    It also means the window appears immediately instead of
                    after a 10-30s model load with nothing on screen.
                    """
                    try:
                        ui.set_state("idle")
                        ui.set_last_exchange("Loading models…")
                        session = build_voice_session(cfg, sys.platform, ptt=talker)
                        session.add_listener(ui.on_voice_event)
                        ui.set_last_exchange(
                            "Just speak — it is listening."
                            if hands_free else
                            "Click Start Listening, then speak."
                        )
                        session.run_forever()
                    except Exception as e:
                        print(traceback.format_exc())
                        ui.on_voice_event("error", e)

                ui._session_runner = build_and_run
                run = ui.run
            else:
                session = build_voice_session(cfg, sys.platform)
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
