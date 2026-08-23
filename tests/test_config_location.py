"""The packaged app needs a config the user can actually edit.

Config was loaded from `Path(__file__).parent / "config.yaml"`. In a frozen
app that resolves inside the bundle, which is wrong three ways: the file is not
shipped there at all, editing anything inside a code-signed bundle invalidates
the signature (and with it the TCC grants), and an app update replaces it.

So a packaged user could never change the model, the allowed roots, or anything
else without rebuilding from source.

Resolution order: a user config in ~/.glimmer-assistant/, then one beside the
module (the dev checkout), then built-in defaults.
"""
from pathlib import Path

from assistant.config import (
    USER_CONFIG_PATH,
    ensure_user_config,
    load_config,
    resolve_config_path,
)


def test_user_config_wins_over_the_packaged_one(tmp_path: Path):
    user = tmp_path / "user.yaml"
    user.write_text("llm_model: user-choice:1b\n")
    packaged = tmp_path / "packaged.yaml"
    packaged.write_text("llm_model: packaged:2b\n")

    assert resolve_config_path(user=user, packaged=packaged) == user


def test_falls_back_to_the_packaged_config_when_no_user_config(tmp_path: Path):
    packaged = tmp_path / "packaged.yaml"
    packaged.write_text("llm_model: packaged:2b\n")

    assert resolve_config_path(user=tmp_path / "absent.yaml", packaged=packaged) == packaged


def test_returns_none_when_neither_exists_so_defaults_apply(tmp_path: Path):
    assert resolve_config_path(
        user=tmp_path / "a.yaml", packaged=tmp_path / "b.yaml"
    ) is None


def test_user_config_actually_changes_the_model(tmp_path: Path):
    """The point of the whole exercise."""
    user = tmp_path / "config.yaml"
    user.write_text("llm_model: muse-glimmer:30b\n")
    cfg = load_config(resolve_config_path(user=user, packaged=tmp_path / "none.yaml"))
    assert cfg.llm_model == "muse-glimmer:30b"


def test_user_config_path_is_outside_any_app_bundle():
    """Editing inside a signed bundle breaks the signature and the TCC grants."""
    p = str(USER_CONFIG_PATH)
    assert ".app/" not in p
    assert p.startswith(str(Path.home()))


def test_ensure_user_config_writes_a_discoverable_template(tmp_path: Path):
    target = tmp_path / "config.yaml"
    created = ensure_user_config(target)

    assert created is True
    text = target.read_text()
    assert "llm_model" in text, "template does not mention the setting people change most"
    assert text.lstrip().startswith("#"), "template should be inert until edited"


def test_ensure_user_config_never_overwrites_an_edited_file(tmp_path: Path):
    target = tmp_path / "config.yaml"
    target.write_text("llm_model: my-careful-choice:8b\n")

    created = ensure_user_config(target)

    assert created is False
    assert "my-careful-choice:8b" in target.read_text()


def test_ensure_user_config_survives_an_unwritable_location(tmp_path: Path):
    """A read-only home must not stop the app from starting."""
    blocked = tmp_path / "nope"
    blocked.write_text("i am a file, not a directory")
    assert ensure_user_config(blocked / "config.yaml") is False
