"""Say something immediately, because the real wait is 15-24 seconds.

Measured time to the first spoken word on real turns: 14.5s with one tool,
23.9s with none. Streaming does not help here -- this model emits ALL of its
reasoning tokens before any content, so there is nothing to stream until
thinking finishes. Suppressing reasoning was measured and rejected: the eval
drops 10/10 to 9/10 and `</think>` leaks into spoken output.

So the remaining lever is not speed, it is silence. An acknowledgement does
not make the answer arrive sooner; it makes the gap read as "working" rather
than "broken", which is the difference the user actually experiences.

Deliberately NOT model-generated: asking the LLM for a filler would cost
another round-trip, which is the thing being worked around.
"""
from __future__ import annotations

import hashlib

# Short, neutral, and not a promise about what the answer will be.
_PHRASES = (
    "One moment.",
    "Let me check.",
    "Working on it.",
    "Just a second.",
    "Looking into that.",
)

# Below this there is no silence worth filling, and acknowledging a fast reply
# just doubles the talking.
_WORTH_ACKNOWLEDGING_SECONDS = 2.0


def should_acknowledge(expected_seconds: float) -> bool:
    return expected_seconds >= _WORTH_ACKNOWLEDGING_SECONDS


def acknowledgement_for(transcript: str) -> str:
    """Pick a phrase. Varied so it does not feel robotic, deterministic so it
    stays testable and does not surprise the user on a repeated request."""
    text = (transcript or "").strip()
    if not text:
        return ""
    digest = hashlib.sha256(text.encode()).digest()
    return _PHRASES[digest[0] % len(_PHRASES)]
