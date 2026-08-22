"""fill_form_field: the last unbuilt tool in spec SS7's web list.

The assistant can read pages but cannot put anything into them. The spec calls
this out as "(gated)" and the gating is the whole design question: typing into
a page is the step just before submitting one, and by the time the model wants
to fill a field it has almost always just READ that page -- which flips session
trust. So this tool must be both CONFIRM tier and outbound, or Rule-of-Two
elevation never fires on the most dangerous web action we support.
"""
from assistant.tools.registry import RiskTier
from assistant.tools.web import make_web_tools


class FakeBrowser:
    def __init__(self, result="filled"):
        self.calls = []
        self.result = result

    def goto(self, url):
        self.calls.append(("goto", url))
        return "title"

    def snapshot(self, url):
        self.calls.append(("snapshot", url))
        return "content"

    def fill(self, url, selector, value):
        self.calls.append(("fill", url, selector, value))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def tools(browser=None):
    return {t.name: t for t in make_web_tools(browser or FakeBrowser())}


def test_fill_form_field_exists():
    assert "fill_form_field" in tools()


def test_fill_delegates_to_the_browser():
    b = FakeBrowser("filled #email")
    out = tools(b)["fill_form_field"].func(
        {"url": "https://example.com/f", "selector": "#email", "value": "a@b.c"}
    )
    assert out == "filled #email"
    assert b.calls == [("fill", "https://example.com/f", "#email", "a@b.c")]


def test_fill_requires_blocking_confirmation():
    """Typing into a page is one step from submitting it."""
    assert tools()["fill_form_field"].risk_tier == RiskTier.CONFIRM


def test_fill_is_outbound_so_rule_of_two_elevation_applies():
    """Filling a field puts data into a remote page: that is exfiltration.

    Without outbound=True, a session that has read an untrusted page could be
    talked into typing private data into an attacker's form with no elevated
    confirmation.
    """
    assert tools()["fill_form_field"].outbound is True


def test_fill_rejects_non_http_schemes_before_touching_the_browser():
    b = FakeBrowser()
    for bad in ("file:///etc/passwd", "javascript:alert(1)", "data:text/html,x"):
        out = tools(b)["fill_form_field"].func(
            {"url": bad, "selector": "#a", "value": "v"}
        )
        assert out.startswith("ERROR:"), bad
    assert b.calls == []


def test_fill_reports_browser_errors_as_strings():
    b = FakeBrowser(RuntimeError("no such element"))
    out = tools(b)["fill_form_field"].func(
        {"url": "https://example.com", "selector": "#missing", "value": "v"}
    )
    assert out.startswith("ERROR:")
    assert "no such element" in out


def test_fill_does_not_echo_the_value_back_into_context():
    """The filled value is often private (an address, a code, a name).

    Echoing it into the tool result would copy it into the transcript and any
    later compaction summary for no benefit.
    """
    b = FakeBrowser("filled #card")
    out = tools(b)["fill_form_field"].func(
        {"url": "https://example.com", "selector": "#card", "value": "SECRET-4242"}
    )
    assert "SECRET-4242" not in out
