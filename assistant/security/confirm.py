from __future__ import annotations

import re
from dataclasses import dataclass

# ESC-initiated sequences (ANSI CSI/OSC etc.), then any remaining C0/C1 controls.
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[@-_].*?(?:\x07|\x1b\\)|\x1b[@-_]")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
_WHITESPACE = re.compile(r"[\t\n\r]+")


def sanitize_preview(text: str) -> str:
    text = _ANSI.sub("", text)
    text = _WHITESPACE.sub(" ", text)
    text = _CONTROL.sub("", text)
    return text.strip()


@dataclass(frozen=True)
class ConfirmRequest:
    tool_name: str
    args: dict
    preview: str


def build_confirm_request(tool_name: str, args: dict) -> ConfirmRequest:
    rendered = tool_name + " " + " ".join(f"{k}={v}" for k, v in args.items())
    return ConfirmRequest(tool_name=tool_name, args=args, preview=sanitize_preview(rendered))
