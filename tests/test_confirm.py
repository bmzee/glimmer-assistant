from assistant.security.confirm import (
    ConfirmRequest,
    build_confirm_request,
    sanitize_preview,
)


def test_sanitize_strips_ansi_and_control_chars():
    dirty = "rm \x1b[31mred\x1b[0m\nline\ttab\x07bell"
    clean = sanitize_preview(dirty)
    assert "\x1b" not in clean
    assert "\x07" not in clean
    assert "\n" not in clean
    assert "\t" not in clean
    assert "red" in clean and "line" in clean and "tab" in clean


def test_build_request_has_name_args_and_clean_preview():
    req = build_confirm_request("run_shell", {"command": "echo \x1b[31mhi"})
    assert isinstance(req, ConfirmRequest)
    assert req.tool_name == "run_shell"
    assert req.args == {"command": "echo \x1b[31mhi"}
    assert "\x1b" not in req.preview
    assert "run_shell" in req.preview
    assert "echo" in req.preview
