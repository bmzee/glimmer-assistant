"""Preflight: tell the user what is wrong, because a bundled app cannot print.

Launched from a .app there is no terminal, and LSUIElement means no Dock icon
either. Every `print()` in main.py goes nowhere. So a missing Ollama, an
unpulled model, or an undownloaded voice model all present identically to the
user: the app silently does nothing.

Preflight turns each of those into a named problem with a concrete remedy, so
the launcher can surface it in a dialog instead of dying quietly.

Every probe is injected: these tests must never touch the network or depend on
what happens to be installed on the machine running them.
"""
from assistant.config import Config
from assistant.preflight import Check, format_problems, run_preflight


def _probes(ollama=True, model=True, voice=True, chromium=True):
    return {
        "ollama_reachable": lambda: ollama,
        "model_present": lambda name: model,
        "voice_models_present": lambda: voice,
        "chromium_present": lambda: chromium,
    }


def test_all_good_reports_no_problems():
    checks = run_preflight(Config(), probes=_probes())
    assert all(c.ok for c in checks), [c for c in checks if not c.ok]
    assert format_problems(checks) == ""


def test_missing_ollama_is_reported_with_a_remedy():
    checks = run_preflight(Config(), probes=_probes(ollama=False))
    bad = [c for c in checks if not c.ok]
    assert bad, "missing Ollama was not reported"
    assert any("ollama" in c.name.lower() for c in bad)
    assert all(c.remedy for c in bad), "a problem with no remedy is not actionable"


def test_unreachable_ollama_does_not_also_claim_the_model_is_missing():
    """Two errors for one cause is noise; the model check cannot run at all."""
    checks = run_preflight(Config(), probes=_probes(ollama=False, model=False))
    failed = [c.name for c in checks if not c.ok]
    assert len([n for n in failed if "model" in n.lower()]) == 0, (
        f"model reported as a separate failure when Ollama is down: {failed}"
    )


def test_missing_model_names_the_configured_model():
    cfg = Config(llm_model="some-model:99b")
    checks = run_preflight(cfg, probes=_probes(model=False))
    bad = [c for c in checks if not c.ok]
    assert any("some-model:99b" in (c.detail + c.remedy) for c in bad), (
        "the remedy must name the model the user actually configured"
    )


def test_voice_models_absent_is_a_warning_not_a_blocker():
    """They download automatically on first run; that is slow, not broken."""
    checks = run_preflight(Config(), probes=_probes(voice=False))
    voice = [c for c in checks if "voice" in c.name.lower()]
    assert voice and not voice[0].blocking


def test_chromium_only_checked_when_web_is_enabled():
    off = run_preflight(Config(enable_web=False), probes=_probes(chromium=False))
    assert not any("chromium" in c.name.lower() for c in off)

    on = run_preflight(Config(enable_web=True), probes=_probes(chromium=False))
    assert any("chromium" in c.name.lower() for c in on)


def test_format_problems_is_readable_and_lists_remedies():
    checks = run_preflight(Config(), probes=_probes(ollama=False))
    text = format_problems(checks)
    assert text
    assert "\n" in text
    assert any(word in text.lower() for word in ("install", "run", "open"))


def test_probe_exceptions_become_failed_checks_not_crashes():
    """A probe that raises must not take the whole app down before it starts."""

    def boom():
        raise OSError("network unreachable")

    probes = _probes()
    probes["ollama_reachable"] = boom
    checks = run_preflight(Config(), probes=probes)
    assert any(not c.ok for c in checks)


def test_blocking_problems_are_distinguishable_from_warnings():
    checks = run_preflight(Config(), probes=_probes(ollama=False, voice=False))
    assert any(c.blocking for c in checks if not c.ok)
    assert any(not c.blocking for c in checks if not c.ok)


def test_check_is_immutable():
    """Checks are reported, not mutated, once produced."""
    c = Check(name="x", ok=True, detail="d", remedy="", blocking=True)
    try:
        c.ok = False
    except Exception:
        return
    raise AssertionError("Check should be frozen")
