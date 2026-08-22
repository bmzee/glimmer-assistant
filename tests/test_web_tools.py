from assistant.tools.registry import RiskTier
from assistant.tools.web import make_web_tools


class FakeBrowser:
    def __init__(self):
        self.visited = []

    def goto(self, url):
        self.visited.append(url)
        return "Example Domain"

    def snapshot(self, url):
        self.visited.append(url)
        return 'heading "Example Domain"\ntext "This domain is for illustrative examples."'


def by_name(tools):
    return {t.name: t for t in tools}


def test_read_page_is_untrusted_and_auto():
    tools = by_name(make_web_tools(browser=FakeBrowser()))
    read = tools["read_page"]
    assert read.risk_tier == RiskTier.AUTO
    assert read.untrusted is True  # web content must be datamarked


def test_search_web_is_untrusted():
    tools = by_name(make_web_tools(browser=FakeBrowser()))
    assert tools["search_web"].untrusted is True


def test_open_url_navigates_and_returns_title():
    fake = FakeBrowser()
    tools = by_name(make_web_tools(browser=fake))
    out = tools["open_url"].func({"url": "https://example.com"})
    assert "Example Domain" in out
    assert fake.visited == ["https://example.com"]


def test_read_page_returns_snapshot_text():
    tools = by_name(make_web_tools(browser=FakeBrowser()))
    out = tools["read_page"].func({"url": "https://example.com"})
    assert "Example Domain" in out
    assert "illustrative examples" in out


def test_rejects_non_http_schemes():
    fake = FakeBrowser()
    tools = by_name(make_web_tools(browser=fake))
    for bad in ["file:///etc/passwd", "javascript:alert(1)", "data:text/html,x"]:
        out = tools["read_page"].func({"url": bad})
        assert out.startswith("ERROR:")
    assert fake.visited == []  # never navigated


def test_browser_errors_become_error_strings():
    class BoomBrowser:
        def goto(self, url):
            raise RuntimeError("browser crashed")

        def snapshot(self, url):
            raise RuntimeError("browser crashed")

    tools = by_name(make_web_tools(browser=BoomBrowser()))
    assert tools["read_page"].func({"url": "https://example.com"}).startswith("ERROR:")
