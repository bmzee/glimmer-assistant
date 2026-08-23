"""Let the user choose a model from what Ollama actually has.

The packaged app has no window and no terminal, so "edit a YAML file" is the
only way to change models today — which nobody discovers. This asks Ollama what
is installed and offers those, once, then remembers the answer.

It must never offer a model that is not pulled: picking one would produce a
confusing failure at first use rather than at selection.
"""
from pathlib import Path

from assistant.model_picker import (
    choose_model,
    installed_models,
    should_prompt,
)


def test_lists_models_from_the_ollama_api():
    payload = {"models": [{"name": "a:1b"}, {"name": "b:2b"}]}
    assert installed_models(fetch=lambda: payload) == ["a:1b", "b:2b"]


def test_sorts_so_the_order_is_stable_between_launches():
    payload = {"models": [{"name": "z:1b"}, {"name": "a:1b"}]}
    assert installed_models(fetch=lambda: payload) == ["a:1b", "z:1b"]


def test_unreachable_ollama_yields_no_models_rather_than_raising():
    def boom():
        raise OSError("connection refused")

    assert installed_models(fetch=boom) == []


def test_prompts_when_no_model_has_been_chosen_yet(tmp_path: Path):
    assert should_prompt(config_path=tmp_path / "absent.yaml") is True


def test_does_not_prompt_once_a_model_is_recorded(tmp_path: Path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("llm_model: chosen:1b\n")
    assert should_prompt(config_path=cfg) is False


def test_a_commented_out_model_still_counts_as_unchosen(tmp_path: Path):
    """The shipped template has llm_model commented; that is not a choice."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text("# llm_model: qwen3.8:27b\n# other: 1\n")
    assert should_prompt(config_path=cfg) is True


def test_choosing_writes_the_selection_to_the_user_config(tmp_path: Path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("# llm_model: qwen3.8:27b\n")

    chosen = choose_model(
        models=["a:1b", "b:2b"],
        ask=lambda models: "b:2b",
        config_path=cfg,
    )

    assert chosen == "b:2b"
    text = cfg.read_text()
    assert "llm_model: b:2b" in text
    assert not text.lstrip().startswith("# llm_model: b:2b")


def test_choosing_preserves_other_settings(tmp_path: Path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("voice_hotkey: alt\nllm_model: old:1b\n")

    choose_model(models=["new:2b"], ask=lambda m: "new:2b", config_path=cfg)

    text = cfg.read_text()
    assert "voice_hotkey: alt" in text, "unrelated settings were lost"
    assert "llm_model: new:2b" in text
    assert "old:1b" not in text


def test_cancelling_the_dialog_changes_nothing(tmp_path: Path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("# llm_model: qwen3.8:27b\n")
    before = cfg.read_text()

    chosen = choose_model(models=["a:1b"], ask=lambda m: None, config_path=cfg)

    assert chosen is None
    assert cfg.read_text() == before


def test_never_offers_a_model_that_is_not_installed(tmp_path: Path):
    """Offering an unpulled model moves the failure to first use."""
    offered = {}
    choose_model(
        models=["only:1b"],
        ask=lambda m: offered.setdefault("list", m) and None,
        config_path=tmp_path / "c.yaml",
    )
    assert offered["list"] == ["only:1b"]


def test_no_models_installed_does_not_prompt(tmp_path: Path):
    """Nothing to choose from: preflight already reports the real problem."""
    asked = []
    chosen = choose_model(
        models=[], ask=lambda m: asked.append(m), config_path=tmp_path / "c.yaml"
    )
    assert chosen is None
    assert asked == []


def test_write_failure_is_not_fatal(tmp_path: Path):
    blocked = tmp_path / "afile"
    blocked.write_text("not a directory")
    chosen = choose_model(
        models=["a:1b"], ask=lambda m: "a:1b", config_path=blocked / "c.yaml"
    )
    assert chosen == "a:1b"  # reported, even though it could not be persisted
