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


def test_sanitize_rejects_carriage_return_spoof():
    """Regression: \\r-based prompt-overwrite spoof."""
    dirty = "safe\r[y/N] malicious"
    clean = sanitize_preview(dirty)
    assert "\r" not in clean
    assert "safe" in clean and "malicious" in clean


def test_sanitize_rejects_osc_with_bel_terminator():
    """Regression: OSC injection with BEL terminator."""
    dirty = "command\x1b]0;title\x07echo"
    clean = sanitize_preview(dirty)
    assert "\x1b" not in clean
    assert "\x07" not in clean
    assert "command" in clean and "echo" in clean


def test_elevated_request_preview_flags_elevation_and_source():
    req = build_confirm_request(
        "send_mail",
        {"to": "bob@example.com"},
        elevated=True,
        trust_sources=("read_mail_message",),
    )
    assert req.elevated is True
    assert req.trust_sources == ("read_mail_message",)
    assert "ELEVATED" in req.preview
    assert "read_mail_message" in req.preview


def test_non_elevated_request_preview_has_no_elevation_marker():
    req = build_confirm_request("send_mail", {"to": "bob@example.com"})
    assert req.elevated is False
    assert "ELEVATED" not in req.preview


def test_sanitize_rejects_8bit_c1_csi():
    """Regression: 8-bit C1 CSI attack."""
    dirty = "before\x9b31mafter"
    clean = sanitize_preview(dirty)
    assert "\x9b" not in clean
    assert "before" in clean and "after" in clean
