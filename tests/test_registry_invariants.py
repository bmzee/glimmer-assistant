"""Registry-wide security invariants.

These would have caught both Plan-4 Criticals automatically:
  - web tools missing outbound=True (un-gated exfiltration after untrusted ingest)
  - open_url missing untrusted=True (attacker-controlled title laundered into context)
Any new tool must be classified here, so the invariant fails loudly rather than
silently shipping an unflagged capability.

Note: MCP-sourced tools are intentionally out of this invariant's scope. Dynamic
per-server names can't be enumerated statically; MCPServerSpec already defaults to
untrusted=True/CONFIRM tier.
"""
from pathlib import Path

import pytest

from assistant.config import Config
from assistant.main import build_loop

# Tools whose results contain content from outside the trust boundary.
# Such a tool MUST be untrusted=True so the loop datamarks it.
EXPECTED_UNTRUSTED = {
    "read_file",           # a downloaded file launders external content
    "list_dir",            # filenames are attacker-chosen (one dropped file = injected text)
    "read_page",
    "search_web",
    "open_url",            # returns the page title (attacker-controlled)
    "list_calendar_events",
    "list_recent_mail",
    "read_mail_message",
    "m365_list_mail",
    "m365_read_mail",
    "m365_list_events",
    "run_shell",           # sandbox allows file-read unconditionally; stdout may contain untrusted content
    "list_windows",        # a browser window title IS the page title (attacker-controlled)
}

# Tools that can transmit data off the machine or change external state.
# Such a tool MUST be outbound=True so Rule-of-Two elevation applies.
EXPECTED_OUTBOUND = {
    "open_url",
    "read_page",
    "search_web",
    "create_calendar_event",
    "draft_mail",
    "send_mail",
    "m365_send_mail",
    "m365_create_event",
    "fill_form_field",    # puts data INTO a remote page: exfiltration
}

# Tools that mutate or transmit MUST NOT be silently auto-approved.
MUST_NOT_BE_AUTO = {
    "create_calendar_event",
    "draft_mail",
    "send_mail",
    "m365_send_mail",
    "m365_create_event",
    "run_shell",
    "quit_app",            # no Tier-1 undo window exists; unsaved work is unrecoverable
    "fill_form_field",     # one step from submitting the form
}


def all_tools(tmp_path):
    cfg = Config(
        allowed_roots=[str(tmp_path)],
        log_path=str(tmp_path / "a.jsonl"),
        enable_web=True,
        enable_apple=True,
        enable_m365=True,
        m365_client_id="test",
    )
    loop = build_loop(cfg, lambda r: False, "darwin")
    tools = {t.name: t for t in loop._registry.available("darwin")}
    # Verify m365 tools are actually constructed (not vacuously skipped by missing config)
    assert {"m365_send_mail", "m365_list_mail"} <= set(tools), (
        f"m365 tools not constructed in fixture; "
        "invariant assertions would be vacuous. Got: {set(tools)}"
    )
    return tools


def test_every_external_content_tool_is_untrusted(tmp_path):
    tools = all_tools(tmp_path)
    missing = [
        name
        for name in EXPECTED_UNTRUSTED
        if name in tools and not tools[name].untrusted
    ]
    assert not missing, (
        f"tools return external content but are not untrusted={missing}; "
        "their output will NOT be datamarked and will not flip session trust"
    )


def test_every_transmitting_tool_is_outbound(tmp_path):
    tools = all_tools(tmp_path)
    missing = [
        name for name in EXPECTED_OUTBOUND if name in tools and not tools[name].outbound
    ]
    assert not missing, (
        f"tools can transmit/modify external state but are not outbound={missing}; "
        "Rule-of-Two elevation will NOT apply after untrusted ingest"
    )


def test_mutating_tools_are_never_auto_tier(tmp_path):
    from assistant.tools.registry import RiskTier

    tools = all_tools(tmp_path)
    bad = [
        name
        for name in MUST_NOT_BE_AUTO
        if name in tools and tools[name].risk_tier == RiskTier.AUTO
    ]
    assert not bad, f"mutating/transmitting tools must not be AUTO tier: {bad}"


def test_every_registered_tool_is_classified(tmp_path):
    """A new tool must be added to one of the tables above (or explicitly listed
    as neither), so nobody ships an unclassified capability by accident."""
    tools = all_tools(tmp_path)
    # Tools that legitimately neither return external content nor transmit.
    NEITHER = {
        "open_app", "open_path",
        # System control: mutate local state only, return no external content.
        "quit_app", "focus_window", "set_volume",
        "screenshot",  # returns the saved path, not image content
    }
    classified = EXPECTED_UNTRUSTED | EXPECTED_OUTBOUND | NEITHER
    unclassified = sorted(set(tools) - classified)
    assert not unclassified, (
        f"unclassified tools {unclassified}: add each to EXPECTED_UNTRUSTED, "
        "EXPECTED_OUTBOUND, and/or NEITHER in this file after deciding its flags"
    )
