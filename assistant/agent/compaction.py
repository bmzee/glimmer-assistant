from __future__ import annotations

_SUMMARY_PREFIX = "[earlier conversation summarized]"


def estimate_tokens(messages: list[dict]) -> int:
    """Cheap character-based token estimate (~4 chars/token). No tokenizer dep."""
    total = 0
    for message in messages:
        content = message.get("content")
        if content:
            total += len(str(content))
        for call in message.get("tool_calls") or []:
            function = call.get("function", {})
            total += len(str(function.get("name", ""))) + len(
                str(function.get("arguments", ""))
            )
    return total // 4


def should_compact(messages: list[dict], max_tokens: int, threshold: float) -> bool:
    return estimate_tokens(messages) > int(max_tokens * threshold)


def _describe(messages: list[dict]) -> str:
    """Structural summary of the middle: which tools ran, and how it went."""
    tools_called: list[str] = []
    for message in messages:
        for call in message.get("tool_calls") or []:
            name = call.get("function", {}).get("name")
            if name and name not in tools_called:
                tools_called.append(name)
    turns = sum(1 for m in messages if m.get("role") == "user")
    parts = [f"{_SUMMARY_PREFIX}: {turns} earlier exchange(s)"]
    if tools_called:
        parts.append("tools used: " + ", ".join(tools_called))
    return ". ".join(parts) + "."


def _safe_tail_start(messages: list[dict], naive_start: int, floor: int) -> int:
    """Never start the tail on a tool message — its parent assistant message
    (carrying the matching tool_call_id) must travel with it. Returns start index
    clamped to [floor, len(messages))."""
    # Guard against out-of-range indices
    start = max(floor, min(naive_start, len(messages) - 1)) if len(messages) > floor else floor
    # Walk backward if we're on a tool message
    while start > floor and start < len(messages) and messages[start].get("role") == "tool":
        start -= 1
    return start


def compact(messages: list[dict], keep_recent: int = 6) -> list[dict]:
    """Anchored compaction: keep the system message and the recent tail verbatim,
    replace the middle with one structural summary. Deterministic and offline —
    it never calls the model, so it cannot fail or cost a round-trip."""
    if not messages:
        return messages

    # Defensive clamping: keep_recent must be in valid range
    keep_recent = max(0, min(keep_recent, len(messages)))

    head = messages[:1] if messages[0].get("role") == "system" else []

    # Compute the naive tail start position, then adjust for tool-message boundaries
    naive_start = len(messages) - keep_recent if keep_recent else len(messages)
    naive_start = max(naive_start, len(head))
    safe_start = _safe_tail_start(messages, naive_start, len(head))

    tail = messages[safe_start:] if safe_start < len(messages) else []
    middle = messages[len(head) : safe_start]
    if len(middle) <= 1:
        return messages
    return [*head, {"role": "user", "content": _describe(middle)}, *tail]
