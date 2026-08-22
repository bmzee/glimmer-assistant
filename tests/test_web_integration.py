import os

import pytest

pytestmark = pytest.mark.integration

skip = pytest.mark.skipif(
    os.environ.get("GLIMMER_INTEGRATION") != "1",
    reason="set GLIMMER_INTEGRATION=1 to run integration tests",
)


@skip
def test_real_browser_reads_example_com():
    from assistant.tools.web import _Browser

    browser = _Browser()
    try:
        text = browser.snapshot("https://example.com")
    finally:
        browser.close()
    assert "Example Domain" in text
