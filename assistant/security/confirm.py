from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# ESC-initiated sequences (ANSI CSI/OSC etc.), then any remaining C0/C1 controls.
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[@-_].*?(?:\x07|\x1b\\)|\x1b[@-_]")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
# U+2028/U+2029 break lines on many terminals just like \n, enabling the same
# prompt-overwrite spoof the \r regression covers, so fold them to spaces too.
_WHITESPACE = re.compile(r"[\t\n\r\u2028\u2029]+")
# Bidi controls (embeddings/overrides U+202A-202E, isolates U+2066-2069,
# LRM/RLM U+200E/200F) let attacker text visually reverse or reorder the real
# arguments — e.g. the recipient of send_mail — on a bidi-honoring terminal,
# and zero-width characters (U+200B-200D, U+FEFF) hide payload entirely. The
# user would then approve something other than what they read, defeating both
# the CONFIRM checkpoint and the Rule-of-Two ELEVATED banner.
_INVISIBLE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]")


def sanitize_preview(text: str) -> str:
    # NFKC first, so fullwidth/compatibility lookalikes collapse into the
    # plain characters the user believes they are reading.
    text = unicodedata.normalize("NFKC", text)
    # Invisibles go before the ANSI pass so a zero-width character cannot
    # split an escape sequence into fragments the ANSI regex would miss.
    text = _INVISIBLE.sub("", text)
    text = _ANSI.sub("", text)
    text = _WHITESPACE.sub(" ", text)
    text = _CONTROL.sub("", text)
    return text.strip()


@dataclass(frozen=True)
class ConfirmRequest:
    tool_name: str
    args: dict
    preview: str
    elevated: bool = False
    trust_sources: tuple[str, ...] = ()


def build_confirm_request(
    tool_name: str,
    args: dict,
    *,
    elevated: bool = False,
    trust_sources: tuple[str, ...] = (),
) -> ConfirmRequest:
    rendered = tool_name + " " + " ".join(f"{k}={v}" for k, v in args.items())
    if elevated:
        sources = ", ".join(sanitize_preview(s) for s in trust_sources) or "an earlier tool"
        rendered = f"[ELEVATED — untrusted content from {sources} is in this session] {rendered}"
    return ConfirmRequest(
        tool_name=tool_name,
        args=args,
        preview=sanitize_preview(rendered),
        elevated=elevated,
        trust_sources=trust_sources,
    )
