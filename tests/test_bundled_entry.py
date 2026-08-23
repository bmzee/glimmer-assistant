"""The bundled entry point must fail loudly, because it cannot fail visibly.

From a .app there is no terminal and no Dock icon. A blocking problem must
reach the user as a dialog and stop startup; a crash must be captured to a log
rather than vanishing. Everything is injected so no test opens a real dialog.
"""
from assistant.bundled import bundled_main
from assistant.capabilities import Capability
from assistant.config import Config
from assistant.preflight import Check


def _check(name, ok, blocking=True):
    return Check(name=name, ok=ok, detail="d", remedy="do the thing",
                 blocking=blocking)


def _caps(granted=True):
    """Inject capabilities: the real probe reads this machine's actual TCC
    state, which would make these tests pass or fail by accident."""
    return [Capability(name="Microphone", granted=granted, required=True,
                       enables="hearing you", how_to_grant="grant it")]


def test_blocking_problem_shows_a_dialog_and_does_not_start():
    shown, started = [], []
    code = bundled_main(
        Config(),
        checks=[_check("Ollama running", False)],
        show=lambda title, msg: shown.append((title, msg)),
        run=lambda: started.append(True),
        capabilities=_caps(),
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
        capabilities=_caps(),
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
        capabilities=_caps(),
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
        capabilities=_caps(),
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
        capabilities=_caps(),
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
        capabilities=_caps(),
    )
    assert log.exists(), "no log written; a bundled crash would be undiagnosable"
    assert "session started" in log.read_text()


def test_missing_required_permission_warns_but_still_starts():
    """A denied grant is invisible otherwise: the hotkey just does nothing.

    Startup continues -- the app is genuinely running, and the user may grant
    the permission without relaunching -- but they are told why it seems dead.
    """
    shown, started = [], []
    code = bundled_main(
        Config(),
        checks=[_check("Ollama running", True)],
        show=lambda t, m: shown.append((t, m)),
        run=lambda: started.append(True),
        capabilities=_caps(granted=False),
    )
    assert started, "app should still run; the user can grant without relaunching"
    assert shown, "a silently-dead hotkey must not go unexplained"
    assert "hearing you" in shown[0][1], "dialog names the permission, not the task"
    assert code == 0
