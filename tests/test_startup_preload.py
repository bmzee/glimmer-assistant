"""Startup must pin the model, or the preload module is dead code.

The 16-29s weight load has to be paid while the user is still opening the app,
not on their first spoken command. That only happens if bundled_main actually
calls it -- so assert the wiring, not just the helper.
"""
from assistant.bundled import bundled_main
from assistant.capabilities import Capability
from assistant.config import Config
from assistant.preflight import Check


def _check(name, ok, blocking=True):
    return Check(name=name, ok=ok, detail="d", remedy="r", blocking=blocking)


def _caps():
    return [Capability(name="Microphone", granted=True, required=True,
                       enables="hearing you", how_to_grant="grant it")]


def _start(cfg=None, **kw):
    calls = []
    bundled_main(
        cfg or Config(),
        checks=[_check("Ollama running", True)],
        show=lambda t, m: None,
        run=lambda: None,
        capabilities=_caps(),
        preload=lambda base_url, model: calls.append((base_url, model)),
        **kw,
    )
    return calls


def test_startup_pins_the_configured_model():
    cfg = Config()
    calls = _start(cfg)

    assert calls, "startup did not preload; the first command pays a 16-29s reload"
    assert calls[0] == (cfg.llm_base_url, cfg.llm_model)


def test_a_blocking_problem_skips_the_preload():
    """No point loading 25GB for an app that is about to refuse to start."""
    calls = []
    code = bundled_main(
        Config(),
        checks=[_check("Ollama running", False)],
        show=lambda t, m: None,
        run=lambda: None,
        capabilities=_caps(),
        preload=lambda base_url, model: calls.append((base_url, model)),
    )

    assert code != 0
    assert not calls


def test_a_failing_preload_does_not_stop_startup():
    started = []

    def boom(base_url, model):
        raise OSError("connection refused")

    code = bundled_main(
        Config(),
        checks=[_check("Ollama running", True)],
        show=lambda t, m: None,
        run=lambda: started.append(True),
        capabilities=_caps(),
        preload=boom,
    )

    assert code == 0
    assert started, "a cold cache must cost a slow turn, not the whole app"
