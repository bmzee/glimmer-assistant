"""Resolve a spoken app name against what is actually installed.

Speech recognition mangles proper nouns. "open chrome" came back as "Open
Grom", which `open -a Grom` turns into an unhelpful failure -- even though the
assistant had everything it needed to notice there is no app called Grom and
that Chrome is one edit away.

For a voice interface this is the common case, not an edge case, so the rule
is: resolve when it is obvious, ASK when it is not, and never silently open
something the user did not mean. Opening the wrong app is worse than admitting
confusion.
"""
from __future__ import annotations

import difflib
from pathlib import Path

_APP_DIRS = (
    Path("/Applications"),
    Path("/System/Applications"),
    Path("/System/Applications/Utilities"),
    Path("~/Applications").expanduser(),
)

# Deliberately high. On a real machine with ~100 apps installed, SOMETHING
# always looks close: the misheard "Grom" (the user said Chrome) scored 0.75
# against "Grok Bot" and would have been opened confidently. String distance
# cannot know what was meant, so anything short of near-certainty becomes a
# question. Asking costs a second; opening the wrong app costs trust.
_CONFIDENT = 0.85
_PLAUSIBLE = 0.5


def installed_apps(dirs=None) -> list[str]:
    names: set[str] = set()
    for directory in dirs or _APP_DIRS:
        try:
            for entry in Path(directory).iterdir():
                if entry.suffix == ".app":
                    names.add(entry.stem)
        except OSError:
            continue  # a missing or unreadable directory is not an error here
    return sorted(names)


def resolve_app_name(spoken: str, installed: list[str] | None = None):
    """Return (match, candidates).

    match       the app to open, when it is unambiguous
    candidates  plausible alternatives to ask the user about, when it is not

    Exactly one of these is ever non-empty.
    """
    spoken = (spoken or "").strip()
    apps = installed if installed is not None else installed_apps()
    if not spoken or not apps:
        return None, []

    lowered = {a.lower(): a for a in apps}
    key = spoken.lower()

    if key in lowered:
        return lowered[key], []

    # People say "chrome", not "Google Chrome". A word-boundary containment
    # match is stronger evidence than fuzzy similarity, so it is checked first.
    contains = [a for a in apps if key in a.lower().split() or key in a.lower()]
    if len(contains) == 1:
        return contains[0], []
    if len(contains) > 1:
        return None, sorted(contains)

    def similarity(app: str) -> float:
        """Best of whole-name and per-word similarity.

        Comparing a short spoken word against a long full name is dominated by
        the length difference: "grom" vs "google chrome" scores ~0.35 and the
        obvious answer is missed. Against the word "chrome" it scores ~0.6.
        People say one word; apps are named several.
        """
        low = app.lower()
        best = difflib.SequenceMatcher(None, key, low).ratio()
        for word in low.split():
            best = max(best, difflib.SequenceMatcher(None, key, word).ratio())
        return best

    scored = sorted(((similarity(a), a) for a in apps), reverse=True)
    best, name = scored[0]
    runner_up = scored[1][0] if len(scored) > 1 else 0.0

    # Confident AND clearly ahead of the next candidate: act on it.
    if best >= _CONFIDENT and best - runner_up > 0.08:
        return name, []

    plausible = [a for score, a in scored if score >= _PLAUSIBLE][:4]
    if plausible:
        return None, plausible
    return None, []
