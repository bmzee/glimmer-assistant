"""Resolve app names against what is actually installed.

Speech recognition mangles proper nouns -- "open chrome" came back as "Open
Grom". Passing that straight to `open -a` fails with an unhelpful error, when
the assistant had everything it needed to notice there is no app called Grom
and that Chrome is one character away.

For a voice interface this is not a nicety: ASR errors on app names are the
common case, not the exception.
"""
from assistant.tools.appnames import resolve_app_name

INSTALLED = [
    "Google Chrome", "Calculator", "Calendar", "Notes", "Safari",
    "Mail", "Terminal", "Visual Studio Code", "Music",
]


def test_exact_match_wins():
    match, candidates = resolve_app_name("Calculator", INSTALLED)
    assert match == "Calculator" and candidates == []


def test_match_is_case_insensitive():
    assert resolve_app_name("calculator", INSTALLED)[0] == "Calculator"


def test_partial_name_matches_the_full_app():
    """People say "chrome", not "Google Chrome"."""
    assert resolve_app_name("Chrome", INSTALLED)[0] == "Google Chrome"


def test_misheard_name_resolves_to_the_obvious_app():
    """The case that started this: 'Grom' should reach Chrome."""
    match, candidates = resolve_app_name("Grom", INSTALLED)
    assert match == "Google Chrome" or "Google Chrome" in candidates


def test_other_plausible_mishearings():
    for heard in ("Crome", "Chrom", "Calcuator", "Safar"):
        match, candidates = resolve_app_name(heard, INSTALLED)
        assert match or candidates, f"{heard!r} produced no suggestion at all"


def test_ambiguous_input_returns_candidates_instead_of_guessing():
    """Two equally plausible apps must become a question, not a coin flip."""
    match, candidates = resolve_app_name("Cal", ["Calculator", "Calendar"])
    assert match is None
    assert set(candidates) == {"Calculator", "Calendar"}


def test_nonsense_returns_nothing_rather_than_a_wild_guess():
    """Opening an unrelated app is worse than admitting confusion."""
    match, candidates = resolve_app_name("zzzqqq", INSTALLED)
    assert match is None
    assert candidates == []


def test_empty_input_is_handled():
    assert resolve_app_name("", INSTALLED) == (None, [])


def test_no_installed_apps_does_not_crash():
    assert resolve_app_name("Chrome", []) == (None, [])


def test_a_closer_but_wrong_app_becomes_a_question():
    """The real-machine failure: 'Grom' (user said Chrome) scored 0.75 against
    'Grok Bot' and was opened confidently. With ~100 apps installed something
    always looks close, so near-misses must ask rather than act."""
    match, candidates = resolve_app_name("Grom", ["Grok Bot", "Google Chrome"])
    assert match is None, f"opened {match!r} on a coin-flip match"
    assert "Google Chrome" in candidates and "Grok Bot" in candidates


def test_a_genuine_typo_still_opens_without_asking():
    """Raising the bar must not make every request a question."""
    assert resolve_app_name("Crome", ["Google Chrome", "Calculator"])[0] == "Google Chrome"
    assert resolve_app_name("Calculatr", ["Calculator", "Calendar"])[0] == "Calculator"
