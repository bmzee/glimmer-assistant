from unittest.mock import create_autospec

import pytest

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


def test_all_web_tools_are_outbound():
    # CRITICAL-1: web tools are a real network-egress channel — Playwright runs
    # in-process, so the sandbox's network-egress denial does not cover them.
    # outbound=True is what makes the Rule-of-Two gate require confirmation once
    # untrusted content has entered the session (the exfiltration leg).
    tools = by_name(make_web_tools(browser=FakeBrowser()))
    assert tools["open_url"].outbound is True
    assert tools["read_page"].outbound is True
    assert tools["search_web"].outbound is True


def test_open_url_is_untrusted():
    # CRITICAL-2: open_url returns page.title(), which is fully attacker-
    # controlled. It must be datamarked and must flip SessionTrust, exactly
    # like read_page/search_web.
    tools = by_name(make_web_tools(browser=FakeBrowser()))
    assert tools["open_url"].untrusted is True


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


def test_snapshot_uses_api_present_on_installed_playwright_page():
    # Autospec fences the fakes to the real installed Playwright surface, so a
    # snapshot() built on an API that upstream has removed fails here rather
    # than only in the (network-bound) integration test.
    sync_api = pytest.importorskip("playwright.sync_api")
    from assistant.tools.web import _Browser

    page = create_autospec(sync_api.Page, instance=True)
    locator = create_autospec(sync_api.Locator, instance=True)
    page.locator.return_value = locator
    locator.aria_snapshot.return_value = (
        '- heading "Example Domain" [level=1]\n'
        "- paragraph: This domain is for illustrative examples."
    )
    context = create_autospec(sync_api.BrowserContext, instance=True)
    context.pages = [page]

    browser = _Browser()
    browser._context = context
    out = browser.snapshot("https://example.com")

    assert page.goto.call_args[0][0] == "https://example.com"
    assert "Example Domain" in out
    assert "illustrative examples" in out


def test_open_url_rejects_non_http_schemes():
    fake = FakeBrowser()
    tools = by_name(make_web_tools(browser=fake))
    for bad in ["file:///etc/passwd", "javascript:alert(1)", "data:text/html,x"]:
        out = tools["open_url"].func({"url": bad})
        assert out.startswith("ERROR:")
    assert fake.visited == []  # never navigated
