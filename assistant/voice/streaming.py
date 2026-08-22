from __future__ import annotations

import re

_SENTENCE = re.compile(r"[^.!?]*[.!?]+|\S[^.!?]*$")


def split_sentences(text: str) -> list[str]:
    return [m.group().strip() for m in _SENTENCE.finditer(text) if m.group().strip()]
