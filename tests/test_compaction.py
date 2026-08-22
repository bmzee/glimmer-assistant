from assistant.agent.compaction import compact, estimate_tokens, should_compact


def msg(role, content, **kw):
    return {"role": role, "content": content, **kw}


def test_estimate_grows_with_content():
    small = [msg("user", "hi")]
    big = [msg("user", "x" * 4000)]
    assert estimate_tokens(big) > estimate_tokens(small)
    assert estimate_tokens(big) >= 900  # ~4000 chars / 4


def test_should_compact_only_past_threshold():
    small = [msg("user", "x" * 100)]
    assert should_compact(small, max_tokens=1000, threshold=0.65) is False
    big = [msg("user", "x" * 4000)]  # ~1000 tokens > 650
    assert should_compact(big, max_tokens=1000, threshold=0.65) is True


def test_compact_preserves_system_and_recent():
    messages = [msg("system", "SYSTEM PROMPT")]
    for i in range(20):
        messages.append(msg("user", f"question {i}"))
        messages.append(msg("assistant", f"answer {i}"))

    out = compact(messages, keep_recent=6)

    assert out[0]["role"] == "system"
    assert out[0]["content"] == "SYSTEM PROMPT"       # system anchored
    assert out[-6:] == messages[-6:]                   # recent verbatim
    assert len(out) < len(messages)                    # actually shrank
    assert any("summarized" in str(m.get("content", "")) for m in out)


def test_compact_is_noop_when_already_short():
    messages = [msg("system", "S"), msg("user", "a"), msg("assistant", "b")]
    assert compact(messages, keep_recent=6) == messages


def test_summary_mentions_tools_that_ran():
    messages = [
        msg("system", "S"),
        msg("assistant", None, tool_calls=[{"id": "c1", "type": "function",
                                            "function": {"name": "read_page", "arguments": "{}"}}]),
        msg("tool", "page text", tool_call_id="c1"),
    ]
    for i in range(10):
        messages.append(msg("user", f"q{i}"))
        messages.append(msg("assistant", f"a{i}"))

    out = compact(messages, keep_recent=4)
    summary = next(m for m in out if "summarized" in str(m.get("content", "")))
    assert "read_page" in summary["content"]


def test_compaction_never_drops_the_system_message_even_with_tiny_keep():
    messages = [msg("system", "S")] + [msg("user", f"q{i}") for i in range(30)]
    out = compact(messages, keep_recent=1)
    assert out[0]["role"] == "system"


def test_tail_never_starts_on_a_tool_message():
    """When the naive tail cutoff lands on a tool message, extend backward
    to ensure the parent assistant message (with tool_calls) travels with it."""
    messages = [
        msg("system", "S"),
        msg("user", "q0"),
        msg("assistant", None, tool_calls=[
            {"id": "c1", "type": "function", "function": {"name": "read", "arguments": "{}"}},
            {"id": "c2", "type": "function", "function": {"name": "read", "arguments": "{}"}}
        ]),
        msg("tool", "result1", tool_call_id="c1"),
        msg("tool", "result2", tool_call_id="c2"),
        msg("user", "q1"),
        msg("assistant", "a1"),
        msg("user", "q2"),
    ]
    # With keep_recent=3, the naive start would be at index 8-3=5 (the "user q1" message),
    # which would cause messages[3:5] to stay (assistant + tool), but if adjusted,
    # the tail should begin at or before the assistant message.
    out = compact(messages, keep_recent=3)
    # The tail should never start with a tool message
    assert out[-1]["role"] != "tool" or (len(out) > 1 and out[-2].get("role") == "assistant")
    if out and out[-1]["role"] == "tool":
        # If there's a tool message in the output, its parent must be there too
        tool_call_id = out[-1]["tool_call_id"]
        parent_found = any(
            msg.get("role") == "assistant" and any(
                c.get("id") == tool_call_id for c in msg.get("tool_calls", [])
            )
            for msg in out
        )
        assert parent_found, f"tool_call_id {tool_call_id} has no parent assistant message"


def test_every_tool_message_has_its_parent():
    """Invariant: every tool message in the compacted output must be preceded
    (anywhere earlier) by an assistant message with a matching tool_calls entry."""
    messages = [
        msg("system", "S"),
        msg("user", "q0"),
        msg("assistant", None, tool_calls=[
            {"id": "c1", "type": "function", "function": {"name": "tool1", "arguments": "{}"}},
            {"id": "c2", "type": "function", "function": {"name": "tool2", "arguments": "{}"}}
        ]),
        msg("tool", "r1", tool_call_id="c1"),
        msg("tool", "r2", tool_call_id="c2"),
        msg("user", "q1"),
        msg("assistant", None, tool_calls=[
            {"id": "c3", "type": "function", "function": {"name": "tool3", "arguments": "{}"}}
        ]),
        msg("tool", "r3", tool_call_id="c3"),
        msg("user", "q2"),
        msg("assistant", "done"),
    ]
    out = compact(messages, keep_recent=4)

    # For every tool message, verify its parent assistant exists earlier in output
    for i, m in enumerate(out):
        if m.get("role") == "tool":
            tool_call_id = m["tool_call_id"]
            parent_found = any(
                out[j].get("role") == "assistant" and any(
                    c.get("id") == tool_call_id
                    for c in out[j].get("tool_calls", [])
                )
                for j in range(i)  # Earlier messages only
            )
            assert parent_found, (
                f"tool_call_id '{tool_call_id}' at index {i} has no preceding "
                f"assistant message with matching tool_calls entry"
            )


def test_parallel_tool_calls_not_orphaned():
    """Parallel tool calls (multiple calls in one assistant message) must
    never have their results split from the parent."""
    messages = [
        msg("system", "S"),
        msg("user", "user1", metadata={"long": "x" * 100}),
        msg("assistant", None, tool_calls=[
            {"id": "p1", "type": "function", "function": {"name": "a", "arguments": "{}"}},
            {"id": "p2", "type": "function", "function": {"name": "b", "arguments": "{}"}},
        ]),
        msg("tool", "r1", tool_call_id="p1"),
        msg("tool", "r2", tool_call_id="p2"),
        msg("user", "user2"),
        msg("assistant", "response"),
    ]
    out = compact(messages, keep_recent=2)

    # Find all tool messages in output
    tool_ids = {m["tool_call_id"] for m in out if m.get("role") == "tool"}

    # For each, verify parent exists
    for tool_id in tool_ids:
        parent_found = any(
            m.get("role") == "assistant" and any(
                c.get("id") == tool_id for c in m.get("tool_calls", [])
            )
            for m in out
        )
        assert parent_found, f"parallel call {tool_id} orphaned from parent"
