"""Registry-wide security invariants.

These would have caught both Plan-4 Criticals automatically:
  - web tools missing outbound=True (un-gated exfiltration after untrusted ingest)
  - open_url missing untrusted=True (attacker-controlled title laundered into context)
Any new tool must be classified here, so the invariant fails loudly rather than
silently shipping an unflagged capability.

Note: MCP-sourced tools are intentionally out of this invariant's scope. Dynamic
per-server names can't be enumerated statically; MCPServerSpec already defaults to
untrusted=True/CONFIRM tier.

The capability cross-checks at the bottom go further: they classify each tool
from its OWN declared interface (name + model-facing description) and require
the security flags to be consistent with that self-description, so a tool that
is under-tagged AND absent from the tables above still fails loudly.
"""
import re
from pathlib import Path

import pytest

from assistant.config import Config
from assistant.main import build_loop
from assistant.tools.registry import RiskTier
from assistant.tools.system import CAPTURE_SUBDIR

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
# NOTE: the gate auto-approves BOTH AUTO and UNDO (no undo mechanism is built),
# so membership here requires CONFIRM or NEVER -- anything below that runs
# without a prompt today, whatever the tier's name promises.
MUST_NOT_BE_AUTO = {
    "create_calendar_event",
    "draft_mail",
    "send_mail",
    "m365_send_mail",
    "m365_create_event",
    "run_shell",
    "quit_app",            # no Tier-1 undo window exists; unsaved work is unrecoverable
    "fill_form_field",     # one step from submitting the form
    "open_path",           # `open` executes .command/.app/binaries OUTSIDE the sandbox
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
    # The gate only prompts at CONFIRM (or Rule-of-Two elevation); UNDO falls
    # through to auto-approve, so "not AUTO" alone would not stop silent runs.
    bad = [
        name
        for name in MUST_NOT_BE_AUTO
        if name in tools and tools[name].risk_tier < RiskTier.CONFIRM
    ]
    assert not bad, (
        f"tools the gate would silently auto-approve (tier below CONFIRM): {bad}"
    )


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


# ---------------------------------------------------------------------------
# Capability cross-checks.
#
# Three of the four Plan-6 findings shared one root cause: the gate and the
# quarantine are correct but driven ENTIRELY by per-tool flags, and tools were
# under-tagged relative to what they actually do (list_dir not untrusted,
# screenshot an unconfined AUTO write, open_path a silently-approved UNDO
# launcher).  The name tables above cannot catch that class: a tool that is
# mis-tagged AND mis-tabled sails through, because both declarations come from
# the same person making the same mistake.
#
# These checks classify every registered tool from its OWN declared interface
# (name + the description shown to the model) and require the security flags
# to be consistent with that self-description.  Signal and flag come from two
# independent declarations, so forgetting a flag no longer hides a capability.
#
# Known limit: a description that HIDES its capability evades a static check.
# But that description also lies to the model and to the user-facing confirm
# preview, which is a reportable bug on its own; and
# test_every_registered_tool_is_classified still forces a human decision for
# every new tool name.
#
# Each check carries a canary assertion (the detector must keep seeing known
# members, so a regex edit cannot quietly turn the invariant vacuous) and a
# stale-entry assertion on its exception list (an entry that no longer earns
# its exemption must be deleted, not accumulate).


def _declared(tool) -> str:
    """A tool's self-description: its name plus the text the model plans from."""
    return (tool.name.replace("_", " ") + " " + tool.description).lower()


# Verbs that declare filesystem/state mutation. Deliberately over-broad:
# a false positive costs one allowlist review; a false negative shipped the
# screenshot arbitrary-write primitive.
_MUTATION_VERBS = re.compile(
    r"\b(writ|sav|overwrit|delet|remov|creat|renam|trash|clobber|destruct"
    r"|eras|wip|truncat|format)[a-z]*\b"
)

# Launch/execute detection is a conjunction (verb AND target) so that
# "open a web page" or "start date" alone do not fire, while "open a
# document with its default application" does.
_LAUNCH_VERBS = re.compile(r"\b(launch|execut|run|runs|ran|running|start|invok|open)[a-z]*\b")
_LAUNCH_TARGETS = re.compile(
    r"\b(app|apps|application|program|file|files|folder|document|binar"
    r"|script|shell|command|executable)[a-z]*\b"
)

# External-content detection: a returning verb AND a content-domain noun
# (or the tool itself admitting "untrusted" while the flag says otherwise --
# the description/flag incoherence that would have shipped list_dir).
_READ_VERBS = re.compile(
    r"\b(list|read|return|search|get|fetch|show|captur|display|report)[a-z]*\b"
)
_CONTENT_NOUNS = re.compile(
    r"\b(director|file|filename|folder|page|web|internet|url|mail|inbox"
    r"|message|email|event|calendar|invitation|title|window|content|output"
    r"|result|subject|sender)[a-z]*\b"
)


def _prove_screenshot_confinement(tools, tmp_path):
    """screenshot's allowlist seat below CONFIRM must be EARNED each run.

    Its tier is AUTO (spec SS8.3 calls screenshot read-only), so a registry
    tier check alone can never distinguish the fixed tool from the original
    arbitrary-write primitive: the fix lives in the implementation.  Re-prove
    the three confinement layers behaviorally; if any is reverted, this fails
    and screenshot must be promoted to CONFIRM or re-confined.

    Assertions match the specific refusal REASON, not just "ERROR", because
    the pre-fix code also returned generic errors ("path outside allowed
    roots") for some probes while happily writing for others.
    """
    shot = tools["screenshot"]
    capture_root = Path(tmp_path) / CAPTURE_SUBDIR

    # Layer 1: a relative path may not traverse out of the capture folder.
    res = shot.func({"path": "../escaped.png"})
    assert "may only be saved inside" in res, (
        f"screenshot no longer confines writes to {capture_root}; the "
        f"arbitrary-write primitive is back (got: {res!r})"
    )

    # Layer 2: only .png, so the capture cannot masquerade as another format.
    res = shot.func({"path": "not-an-image.txt"})
    assert "must end in .png" in res, (
        f"screenshot accepted a non-.png target (got: {res!r})"
    )

    # Layer 3a: never truncate an existing file.
    capture_root.mkdir(parents=True, exist_ok=True)
    (capture_root / "existing.png").write_bytes(b"user data")
    res = shot.func({"path": "existing.png"})
    assert "refusing to overwrite" in res, (
        f"screenshot will clobber existing files (got: {res!r})"
    )

    # Layer 3b: the configured audit log (wired protected by build_loop) is
    # refused even by absolute path -- the original attack aimed screencapture
    # at the action log to destroy the audit trail.
    res = shot.func({"path": str(Path(tmp_path) / "a.jsonl")})
    assert "protected" in res, (
        f"screenshot can overwrite the audit log again (got: {res!r})"
    )


# Write-capable tools allowed below CONFIRM.  Membership is not a comment,
# it is a live obligation: the mapped probe re-proves the safety claim
# against the registered tool object on every run.
WRITE_CAPABLE_BUT_SAFE = {
    # Confined to one dedicated capture folder, .png-only, never overwrites,
    # audit log denylisted (fix 84d55c8). Kept AUTO per spec SS8.3.
    "screenshot": _prove_screenshot_confinement,
}


def test_write_capable_tools_require_confirm_or_proven_confinement(tmp_path):
    tools = all_tools(tmp_path)
    detected = {n for n, t in tools.items() if _MUTATION_VERBS.search(_declared(t))}
    # Canary: the detector must keep seeing the known write-capable tools.
    assert {"screenshot", "run_shell"} <= detected, (
        f"mutation detector went blind (detected only {sorted(detected)}); "
        "fix the regex, do not delete this check"
    )
    unsafe = sorted(
        n
        for n in detected
        if tools[n].risk_tier < RiskTier.CONFIRM and n not in WRITE_CAPABLE_BUT_SAFE
    )
    assert not unsafe, (
        f"tools declaring write/delete capability but auto-approved by the gate: "
        f"{unsafe}; raise to CONFIRM or add a WRITE_CAPABLE_BUT_SAFE entry with "
        "a probe that proves the confinement"
    )
    stale = sorted(
        n
        for n in WRITE_CAPABLE_BUT_SAFE
        if n not in tools or n not in detected or tools[n].risk_tier >= RiskTier.CONFIRM
    )
    assert not stale, (
        f"stale WRITE_CAPABLE_BUT_SAFE entries {stale}: the tool is gone, "
        "undetected, or now >= CONFIRM -- delete the entry"
    )
    for name, prove in WRITE_CAPABLE_BUT_SAFE.items():
        prove(tools, tmp_path)


# Tools that describe launching/opening but stay below CONFIRM. Comments are
# the justification the exemption rests on; if the claim stops being true,
# the exemption must go.
LAUNCH_CAPABLE_BUT_SAFE = {
    # `open -a <name>` targets an INSTALLED application by name; it cannot be
    # pointed at an attacker-dropped path, unlike open_path (decision ca3d966).
    "open_app",
}


def test_exec_or_launch_capable_tools_require_confirm(tmp_path):
    tools = all_tools(tmp_path)
    detected = {
        n
        for n, t in tools.items()
        if _LAUNCH_VERBS.search(_declared(t)) and _LAUNCH_TARGETS.search(_declared(t))
    }
    # Canary: must keep seeing the tools that motivated this invariant.
    assert {"open_path", "open_app", "run_shell"} <= detected, (
        f"launch/exec detector went blind (detected only {sorted(detected)})"
    )
    # The gate auto-approves everything below CONFIRM (UNDO included: no undo
    # mechanism exists), so one injected instruction naming an executable
    # would run it with no prompt -- the original open_path hole.
    unsafe = sorted(
        n
        for n in detected
        if tools[n].risk_tier < RiskTier.CONFIRM and n not in LAUNCH_CAPABLE_BUT_SAFE
    )
    assert not unsafe, (
        f"tools declaring launch/execute capability but auto-approved by the "
        f"gate: {unsafe}; raise to CONFIRM or justify in LAUNCH_CAPABLE_BUT_SAFE"
    )
    stale = sorted(
        n
        for n in LAUNCH_CAPABLE_BUT_SAFE
        if n not in tools or n not in detected or tools[n].risk_tier >= RiskTier.CONFIRM
    )
    assert not stale, f"stale LAUNCH_CAPABLE_BUT_SAFE entries: {stale}"


# Tools whose description matches the external-content detector but whose
# RESULT string is genuinely self-generated, so there is nothing to datamark.
SELF_GENERATED_RESULT = {
    # Returns only the capture path the tool itself validated; the pixels
    # never enter the model context.
    "screenshot",
}


def test_tools_describing_external_content_are_untrusted(tmp_path):
    tools = all_tools(tmp_path)

    def declares_external(t) -> bool:
        text = _declared(t)
        if "untrusted" in text:
            # The description warns the model the data is untrusted: the flag
            # saying otherwise is exactly the incoherence that ships a
            # quarantine bypass.
            return True
        return bool(_READ_VERBS.search(text) and _CONTENT_NOUNS.search(text))

    detected = {n for n, t in tools.items() if declares_external(t)}
    # Canary uses tools whose descriptions do NOT contain the word
    # "untrusted", proving the verb+noun path works on its own -- list_dir's
    # pre-fix description ("List the entries in a directory") had no warning.
    assert {"list_dir", "list_windows"} <= detected, (
        f"external-content detector went blind (detected only {sorted(detected)})"
    )
    missing = sorted(
        n for n in detected - SELF_GENERATED_RESULT if not tools[n].untrusted
    )
    assert not missing, (
        f"tools whose results carry externally-influenced strings but are not "
        f"untrusted={missing}; their output will enter the planning context "
        "un-datamarked and will not flip session trust (the list_dir hole)"
    )
    stale = sorted(
        n
        for n in SELF_GENERATED_RESULT
        if n not in tools or n not in detected or tools[n].untrusted
    )
    assert not stale, f"stale SELF_GENERATED_RESULT entries: {stale}"
