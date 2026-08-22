from assistant.tools.apple import _esc, make_apple_tools
from assistant.tools.registry import RiskTier


class FakeRunner:
    def __init__(self, result="ok"):
        self.result = result
        self.scripts = []

    def __call__(self, script):
        self.scripts.append(script)
        return self.result


def by_name(tools):
    return {t.name: t for t in tools}


def test_escaping_neutralizes_quotes_and_backslashes():
    assert _esc('say "hi"') == 'say \\"hi\\"'
    assert _esc("back\\slash") == "back\\\\slash"


def test_mail_and_calendar_reads_are_untrusted():
    tools = by_name(make_apple_tools(runner=FakeRunner()))
    for name in ("list_calendar_events", "list_recent_mail", "read_mail_message"):
        assert tools[name].untrusted is True, name


def test_outbound_tools_are_confirm_and_outbound():
    tools = by_name(make_apple_tools(runner=FakeRunner()))
    for name in ("create_calendar_event", "draft_mail", "send_mail"):
        assert tools[name].risk_tier == RiskTier.CONFIRM, name
        assert tools[name].outbound is True, name


def test_send_mail_escapes_injected_quotes():
    runner = FakeRunner()
    tools = by_name(make_apple_tools(runner=runner))
    tools["send_mail"].func(
        {"to": "a@b.com", "subject": 'evil" & do shell script "rm -rf /', "body": "hi"}
    )
    script = runner.scripts[0]
    # the raw injection sequence must not appear unescaped
    assert 'evil" & do shell script' not in script
    assert '\\"' in script  # it was escaped


def test_tcc_error_includes_remediation():
    class BoomRunner:
        def __call__(self, script):
            raise RuntimeError("execution error: Not authorised to send Apple events to Mail. (-1743)")

    tools = by_name(make_apple_tools(runner=BoomRunner()))
    out = tools["list_recent_mail"].func({"count": 3})
    assert out.startswith("ERROR:")
    assert "Automation" in out  # tells the user how to fix it


def test_generic_error_becomes_error_string():
    class BoomRunner:
        def __call__(self, script):
            raise RuntimeError("some other failure")

    tools = by_name(make_apple_tools(runner=BoomRunner()))
    assert tools["list_calendar_events"].func({"days_ahead": 7}).startswith("ERROR:")


def test_calendar_name_produces_single_calendar_script():
    runner = FakeRunner()
    tools = by_name(make_apple_tools(runner=runner))
    tools["list_calendar_events"].func({"days_ahead": 7, "calendar_name": "Work"})
    script = runner.scripts[0]
    assert 'calendar "Work"' in script
    assert "repeat with cal in calendars" not in script


def test_omitting_calendar_name_searches_all_calendars():
    runner = FakeRunner()
    tools = by_name(make_apple_tools(runner=runner))
    tools["list_calendar_events"].func({"days_ahead": 7})
    script = runner.scripts[0]
    assert "repeat with cal in calendars" in script
    assert 'calendar "' not in script


def test_calendar_name_with_quote_is_escaped():
    runner = FakeRunner()
    tools = by_name(make_apple_tools(runner=runner))
    tools["list_calendar_events"].func(
        {"days_ahead": 7, "calendar_name": 'evil" & do shell script "rm -rf /'}
    )
    script = runner.scripts[0]
    assert 'evil" & do shell script' not in script
    assert '\\"' in script


def test_calendar_read_requests_extended_timeout():
    # The all-calendars "whose" filter is slow enough to blow past the
    # default 30s subprocess timeout, so the calendar read must ask for a
    # longer budget when the runner supports it.
    seen_timeouts = []

    def runner(script, timeout=30):
        seen_timeouts.append(timeout)
        return "ok"

    tools = by_name(make_apple_tools(runner=runner))
    tools["list_calendar_events"].func({"days_ahead": 7})
    assert seen_timeouts == [120]


def test_other_apple_calls_do_not_request_extended_timeout():
    seen_timeouts = []

    def runner(script, timeout=30):
        seen_timeouts.append(timeout)
        return "ok"

    tools = by_name(make_apple_tools(runner=runner))
    tools["list_recent_mail"].func({"count": 3})
    assert seen_timeouts == [30]
