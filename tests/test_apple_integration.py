import os
import sys

import pytest

pytestmark = pytest.mark.integration

skip = pytest.mark.skipif(
    os.environ.get("GLIMMER_INTEGRATION") != "1" or sys.platform != "darwin",
    reason="set GLIMMER_INTEGRATION=1 on macOS to run Apple integration tests",
)


@skip
def test_real_calendar_listing_does_not_error():
    """Calendar automation is granted on this machine; Mail is not (TCC -1743).

    This test asserts we can reach Calendar at all — it does not assert on the
    user's actual events.
    """
    from assistant.tools.apple import make_apple_tools

    tools = {t.name: t for t in make_apple_tools()}
    out = tools["list_calendar_events"].func({"days_ahead": 7})
    assert not out.startswith("ERROR:"), out


@skip
def test_mail_blocked_reports_remediation_or_works():
    """Mail may be TCC-blocked; either way the tool must not crash."""
    from assistant.tools.apple import make_apple_tools

    tools = {t.name: t for t in make_apple_tools()}
    out = tools["list_recent_mail"].func({"count": 1})
    if out.startswith("ERROR:"):
        assert "Automation" in out  # actionable remediation
