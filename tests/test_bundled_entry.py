"""The bundled entry point must fail loudly, because it cannot fail visibly.

From a .app there is no terminal and no Dock icon. A blocking problem must
reach the user as a dialog and stop startup; a crash must be captured to a log
rather than vanishing. Everything is injected so no test opens a real dialog.
"""
from assistant.bundled import bundled_main
from assistant.config import Config
from assistant.preflight import Check


def _check(name, ok, blocking=True):
    return Check(name=name, ok=ok, detail="d", remedy="do the thing",
                 blocking=blocking)


def test_blocking_problem_shows_a_dialog_and_does_not_start():
    shown, started = [], []
    code = bundled_main(
        Config(),
        checks=[_check("Ollama running", False)],
        show=lambda title, msg: shown.append((title, msg)),
        run=lambda: started.append(True),
    )
    assert code != 0
    assert shown, "user got no dialog for a blocking problem"
    assert "do the thing" in shown[0][1], "dialog omitted the remedy"
    assert not started, "session started despite a blocking problem"


def test_warnings_do_not_prevent_startup():
    shown, started = [], []
    code = bundled_main(
        Config(),
        checks=[_check("Voice models", False, blocking=False)],
        show=lambda t, m: shown.append((t, m)),
        run=lambda: started.append(True),
    )
    assert code == 0
    assert started, "a non-blocking warning stopped startup"


def test_clean_preflight_starts_without_bothering_the_user():
    shown, started = [], []
    code = bundled_main(
        Config(),
        checks=[_check("Ollama running", True)],
        show=lambda t, m: shown.append((t, m)),
        run=lambda: started.append(True),
    )
    assert code == 0
    assert started
    assert not shown, "clean startup should not raise a dialog"


def test_a_crash_during_the_session_is_surfaced_not_swallowed():
    shown = []

    def boom():
        raise RuntimeError("model exploded")

    code = bundled_main(
        Config(),
        checks=[_check("Ollama running", True)],
        show=lambda t, m: shown.append((t, m)),
        run=boom,
    )
    assert code != 0
    assert shown, "a crash produced no dialog: the app would vanish silently"
    assert "model exploded" in shown[0][1]


def test_keyboard_interrupt_is_a_clean_exit_not_a_crash_dialog():
    shown = []

    def quit_():
        raise KeyboardInterrupt

    code = bundled_main(
        Config(),
        checks=[_check("Ollama running", True)],
        show=lambda t, m: shown.append((t, m)),
        run=quit_,
    )
    assert code == 0
    assert not shown


def test_writes_a_log_file_so_failures_are_diagnosable(tmp_path):
    log = tmp_path / "glimmer.log"
    bundled_main(
        Config(),
        checks=[_check("Ollama running", True)],
        show=lambda t, m: None,
        run=lambda: print("session started"),
        log_path=log,
    )
    assert log.exists(), "no log written; a bundled crash would be undiagnosable"
    assert "session started" in log.read_text()
