from __future__ import annotations

import stat
from pathlib import Path

from assistant.security.paths import PathNotAllowedError, resolve_safe
from assistant.tools.adapters.base import PlatformAdapter
from assistant.tools.registry import RiskTier, Tool

# macOS `open` EXECUTES these types instead of displaying them, and the adapter
# runs `open` with no sandbox-exec wrap (only run_shell is sandboxed). A repo
# cloned from an attacker keeps +x and carries no quarantine attribute, so
# Gatekeeper never prompts either: opening one of these is arbitrary code
# execution. Refused outright -- a confirm prompt is no defence when the user
# cannot tell a payload from a document. Compared case-insensitively because
# APFS is case-insensitive: Foo.COMMAND executes just like foo.command.
_EXECUTED_BY_OPEN = {
    ".command", ".app", ".workflow", ".tool", ".scpt",
    ".sh", ".zsh", ".bash",
}


def make_app_tools(adapter: PlatformAdapter, allowed_roots: list[Path]) -> list[Tool]:
    def open_app(args: dict) -> str:
        return adapter.launch_app(args["name"])

    def open_path(args: dict) -> str:
        try:
            p = resolve_safe(args["path"], allowed_roots)
        except PathNotAllowedError as e:
            return f"ERROR: {e}"
        if p.suffix.lower() in _EXECUTED_BY_OPEN:
            return (
                f"ERROR: refusing to open {p.name}: this file type is executed, "
                "not displayed. open_path is for documents and folders only."
            )
        # Extension checks alone are bypassable (a Mach-O binary or shebang
        # script needs no extension); the user-executable bit is what makes
        # `open` run a plain file, so refuse on the bit itself. Directories
        # are exempt: +x there only means traversal, and executable bundles
        # were already caught by extension above.
        try:
            if p.is_file() and (p.stat().st_mode & stat.S_IXUSR):
                return (
                    f"ERROR: refusing to open {p.name}: it is marked executable "
                    "and would be run, not displayed."
                )
        except OSError as e:
            return f"ERROR: {e}"
        return adapter.open_path(str(p))

    return [
        Tool(
            name="open_app",
            description="Launch (or bring to front) an application by name, e.g. 'Notes'.",
            parameters={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
            risk_tier=RiskTier.UNDO,
            platforms=("darwin", "win32"),
            func=open_app,
        ),
        Tool(
            name="open_path",
            description="Open a document or folder with its default application.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            # CONFIRM, not UNDO: the gate auto-approves UNDO (no undo exists),
            # and this call crosses the sandbox boundary -- `open` runs
            # un-sandboxed against an arbitrary allowed-root path. The user
            # must see the exact path before it launches anything.
            risk_tier=RiskTier.CONFIRM,
            platforms=("darwin", "win32"),
            func=open_path,
        ),
    ]
