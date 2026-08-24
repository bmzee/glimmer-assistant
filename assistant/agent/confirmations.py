"""Confirm a completed action from the tool result, not from a second model call.

Profiled on a real turn: "open the calculator" spends 3.1s deciding, 0.08s
actually opening it, then 1.2s asking the model to compose "Calculator is now
open and ready." The app already knows that -- the tool said so.

Only ACTIONS qualify. A query's answer is its result (read_file returns the
text, list_dir the entries), and no template can stand in for that, so those
return None and the model narrates as before.

Every phrase names its subject. "Done." is useless when speech recognition may
have heard the wrong app -- the user needs to hear WHICH app opened to catch
"Grom" being resolved to the wrong thing.
"""
from __future__ import annotations

# A tool result the executor marks as failed. Confirming success off one of
# these would be the worst possible outcome: the user is told the action
# happened when it did not.
_FAILURE_PREFIXES = ("ERROR", "DENIED")


def _named(args: dict, verb: str) -> str | None:
    name = str(args.get("name") or "").strip()
    return f"{verb} {name}." if name else None


_TEMPLATES = {
    "open_app": lambda args: _named(args, "Opening"),
    "quit_app": lambda args: _named(args, "Closing"),
    "focus_window": lambda args: _named(args, "Switching to"),
    "set_volume": lambda args: (
        f"Volume set to {args['level']}." if args.get("level") is not None else None
    ),
}


def is_action(tool_name: str) -> bool:
    return tool_name in _TEMPLATES


def confirmation_for(tool_name: str, args: dict, result: str) -> str | None:
    """A short spoken confirmation, or None to let the model narrate."""
    template = _TEMPLATES.get(tool_name)
    if template is None:
        return None
    if str(result or "").lstrip().upper().startswith(_FAILURE_PREFIXES):
        return None
    try:
        return template(args or {})
    except Exception:
        return None  # a malformed argument is the model's to explain, not ours
