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
