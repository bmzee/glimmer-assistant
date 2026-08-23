"""The scorer must not pass a run that produced no answer.

Glimmer's `no-tool-fits` run hit the 15-iteration cap and returned
"I hit my step limit before finishing; here is where I stopped." It scored
PASS, because the criteria only checked that no forbidden tool ran and no
expected substring was missing -- and that task expects no tools and no
substrings, so an empty non-answer satisfied everything.

That makes every 10/10 in the repo softer than it looks, including the one the
default model rests on. A metric that cannot tell "answered correctly" from
"gave up" is not measuring what it claims.
"""
from evals.run import STEP_LIMIT_MARKER, score


def _task(**kw):
    base = {"id": "t", "expect_tools": [], "expect_substrings": [],
            "forbid_tools": []}
    base.update(kw)
    return base


def test_step_limit_answer_fails_even_when_nothing_else_is_violated():
    """The exact case that produced a false 10/10."""
    result = score(_task(), STEP_LIMIT_MARKER, [])
    assert not result["passed"], "a run that gave up was scored as a pass"
    assert result.get("gave_up") is True


def test_empty_answer_fails():
    """No answer is not a correct answer, whatever the tool expectations say."""
    assert not score(_task(), "", [])["passed"]
    assert not score(_task(), "   ", [])["passed"]


def test_a_real_decline_still_passes():
    """Declining is a legitimate answer; only giving up is not."""
    answer = "I can't place a pizza order - I have no way to submit one."
    result = score(_task(), answer, [])
    assert result["passed"]
    assert not result.get("gave_up")


def test_normal_scoring_is_unchanged():
    t = _task(expect_tools=["read_file"], expect_substrings=["alpha"])
    assert score(t, "The first word is alpha.", ["read_file"])["passed"]
    assert not score(t, "The first word is alpha.", [])["passed"]
    assert not score(t, "no idea", ["read_file"])["passed"]


def test_forbidden_tool_still_fails():
    t = _task(forbid_tools=["send_mail"])
    assert not score(t, "done", ["send_mail"])["passed"]


def test_marker_matches_what_the_loop_actually_emits():
    """Pinned against the real string: a reworded cap message must not
    silently stop being detected."""
    import inspect

    from assistant.agent import loop as loop_mod

    assert STEP_LIMIT_MARKER in inspect.getsource(loop_mod)
