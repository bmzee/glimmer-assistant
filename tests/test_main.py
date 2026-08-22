from assistant.config import Config
from assistant.main import build_loop


def test_build_loop_darwin_registers_expected_tools(tmp_path):
    cfg = Config(
        allowed_roots=[str(tmp_path)],
        log_path=str(tmp_path / "a.jsonl"),
        enable_web=False,
        enable_apple=False,
    )
    loop = build_loop(cfg, confirmer=lambda req: False, platform="darwin")
    names = {t.name for t in loop._registry.available("darwin")}
    assert names == {"list_dir", "read_file", "open_app", "open_path", "run_shell"}


def test_build_loop_win32_gets_cross_platform_tools_only(tmp_path):
    cfg = Config(
        allowed_roots=[str(tmp_path)],
        log_path=str(tmp_path / "a.jsonl"),
        enable_web=False,
        enable_apple=False,
    )
    loop = build_loop(cfg, confirmer=lambda req: False, platform="win32")
    names = {t.name for t in loop._registry.available("win32")}
    # win32 has no adapter yet (Plan 2+), so only stdlib file tools register
    assert names == {"list_dir", "read_file"}


def test_build_voice_session_wires_components(tmp_path):
    from assistant.main import build_voice_session

    class FakePTT:
        def capture_utterance(self):
            return None

    class FakeSTT:
        def transcribe(self, audio, sr):
            return ""

    class FakeTTS:
        def speak(self, text):
            pass

    cfg = Config(allowed_roots=[str(tmp_path)], log_path=str(tmp_path / "a.jsonl"))
    session = build_voice_session(
        cfg, platform="darwin", stt=FakeSTT(), tts=FakeTTS(), ptt=FakePTT()
    )
    # smoke: one cycle with a None utterance does nothing and does not raise
    session.run_once()


def test_voice_event_printer_formats(capsys):
    from assistant.main import _voice_event_printer

    _voice_event_printer("transcribed", "hi")
    _voice_event_printer("answered", "yo")
    _voice_event_printer("error", RuntimeError("x"))

    out = capsys.readouterr().out
    assert "you said: hi" in out
    assert "assistant: yo" in out
    assert "[error]" in out


def test_build_loop_registers_web_tools_when_enabled(tmp_path):
    from assistant.config import Config
    from assistant.main import build_loop

    cfg = Config(
        allowed_roots=[str(tmp_path)],
        log_path=str(tmp_path / "a.jsonl"),
        enable_web=True,
        enable_apple=False,
    )
    loop = build_loop(cfg, lambda r: False, "darwin")
    names = {t.name for t in loop._registry.available("darwin")}
    assert {"open_url", "read_page", "search_web"} <= names


def test_build_loop_can_disable_groups(tmp_path):
    from assistant.config import Config
    from assistant.main import build_loop

    cfg = Config(
        allowed_roots=[str(tmp_path)],
        log_path=str(tmp_path / "a.jsonl"),
        enable_web=False,
        enable_apple=False,
        enable_m365=False,
    )
    loop = build_loop(cfg, lambda r: False, "darwin")
    names = {t.name for t in loop._registry.available("darwin")}
    assert "read_page" not in names
    assert "send_mail" not in names
    assert "list_dir" in names  # core tools still present


def test_build_loop_registers_apple_tools_on_darwin(tmp_path):
    from assistant.config import Config
    from assistant.main import build_loop

    cfg = Config(
        allowed_roots=[str(tmp_path)],
        log_path=str(tmp_path / "a.jsonl"),
        enable_web=False,
        enable_apple=True,
    )
    loop = build_loop(cfg, lambda r: False, "darwin")
    names = {t.name for t in loop._registry.available("darwin")}
    assert {"list_calendar_events", "send_mail"} <= names


def test_m365_requires_client_id(tmp_path):
    from assistant.config import Config
    from assistant.main import build_loop

    cfg = Config(
        allowed_roots=[str(tmp_path)],
        log_path=str(tmp_path / "a.jsonl"),
        enable_web=False,
        enable_apple=False,
        enable_m365=True,
        m365_client_id="",  # not configured -> tools must NOT register
    )
    loop = build_loop(cfg, lambda r: False, "darwin")
    names = {t.name for t in loop._registry.available("darwin")}
    assert "m365_send_mail" not in names


def test_trust_is_shared_between_gate_and_loop(tmp_path):
    from assistant.config import Config
    from assistant.main import build_loop

    cfg = Config(allowed_roots=[str(tmp_path)], log_path=str(tmp_path / "a.jsonl"))
    loop = build_loop(cfg, lambda r: False, "darwin")
    assert loop._trust is not None
    assert loop._gate._trust is loop._trust  # same object, so elevation works
