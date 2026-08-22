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


def compact(messages: list[dict], keep_recent: int = 6) -> list[dict]:
    """Anchored compaction: keep the system message and the recent tail verbatim,
    replace the middle with one structural summary. Deterministic and offline —
    it never calls the model, so it cannot fail or cost a round-trip."""
    if not messages:
        return messages
    head = messages[:1] if messages[0].get("role") == "system" else []
    tail = messages[len(messages) - keep_recent :] if keep_recent else []
    middle = messages[len(head) : len(messages) - len(tail)]
    if len(middle) <= 1:
        return messages
    return [*head, {"role": "user", "content": _describe(middle)}, *tail]
