from __future__ import annotations

import stat
from pathlib import Path

from assistant.security.paths import PathNotAllowedError, resolve_safe
from assistant.tools.adapters.base import PlatformAdapter
from assistant.tools.registry import RiskTier, Tool

# macOS `open` hands a file to its LaunchServices handler, and many handlers
# EXECUTE rather than display. The adapter runs `open` with no sandbox-exec wrap
# (only run_shell is sandboxed), and a repo cloned from an attacker keeps +x and
# carries no quarantine attribute, so Gatekeeper never prompts either: opening
# one of these is arbitrary code execution.
#
# This was first written as a BLOCKLIST of dangerous suffixes. A red-team
# re-attack walked around it with `.terminal` -- an ordinary plist, no execute
# bit, absent from the list -- whose CommandString Terminal.app runs on open,
# and demonstrated code execution end to end through the real tool. The bug was
# structural: enumerating dangerous types permits every type nobody listed, and
# the set (.terminal, .webloc, .pkg, .inetloc, .url, ...) cannot be completed by
# hand or kept current across macOS releases.
#
# So the rule is inverted to DENY BY DEFAULT, matching the posture the SBPL
# sandbox profile already uses: allow known-inert document types, refuse
# everything else. Compared case-insensitively because APFS is case-insensitive
# -- Foo.TERMINAL executes just like foo.terminal.
_SAFE_DOCUMENT_SUFFIXES = frozenset({
    # plain text and data
    ".txt", ".md", ".markdown", ".rtf", ".log", ".csv", ".tsv",
    ".json", ".xml", ".yaml", ".yml", ".toml", ".ini", ".conf",
    # documents
    ".pdf", ".doc", ".docx", ".odt", ".pages", ".epub",
    ".xls", ".xlsx", ".ods", ".numbers",
    ".ppt", ".pptx", ".odp", ".key",
    # images (.svg is deliberately absent: it can carry script and some
    # handlers render it in a browser)
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".tif",
    ".heic", ".heif", ".webp", ".ico",
    # audio and video
    ".mp3", ".m4a", ".wav", ".aac", ".flac", ".aiff",
    ".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm",
    # archives: expansion is not execution
    ".zip",
})

# Kept only to give the model a precise reason instead of the generic refusal.
# Security does not depend on this list being complete -- the allowlist above
# is what actually decides.
_KNOWN_EXECUTING = frozenset({
    ".command", ".app", ".workflow", ".tool", ".scpt", ".scptd",
    ".sh", ".zsh", ".bash", ".terminal", ".term", ".webloc", ".inetloc",
    ".url", ".pkg", ".mpkg", ".dmg", ".applescript", ".shortcut", ".bundle",
})


def make_app_tools(adapter: PlatformAdapter, allowed_roots: list[Path]) -> list[Tool]:
    def open_app(args: dict) -> str:
        return adapter.launch_app(args["name"])

    def open_path(args: dict) -> str:
        try:
            p = resolve_safe(args["path"], allowed_roots)
        except PathNotAllowedError as e:
            return f"ERROR: {e}"
        suffix = p.suffix.lower()
        try:
            is_dir = p.is_dir()
            is_file = p.is_file()
            mode = p.stat().st_mode if (is_dir or is_file) else 0
        except OSError as e:
            return f"ERROR: {e}"

        if is_dir:
            # Bundles ARE directories -- .app, .workflow, .bundle -- and `open`
            # launches them. The executable-bit check below cannot catch this
            # because +x on a directory only means traversal. A plain folder
            # carries no suffix, so that is the discriminator.
            if suffix:
                return (
                    f"ERROR: refusing to open {p.name}: a directory with an "
                    "extension is an application bundle, which would be "
                    "launched. open_path is for documents and plain folders."
                )
            return adapter.open_path(str(p))

        if suffix not in _SAFE_DOCUMENT_SUFFIXES:
            if suffix in _KNOWN_EXECUTING:
                return (
                    f"ERROR: refusing to open {p.name}: this file type is "
                    "executed, not displayed. open_path is for documents and "
                    "folders only."
                )
            return (
                f"ERROR: refusing to open {p.name}: "
                f"{suffix or 'files without an extension'} is not a recognised "
                "document type, and macOS may hand it to a handler that runs "
                "it. open_path allows known document types only."
            )

        # Even an allowed suffix is refused when marked executable: a Mach-O
        # binary or shebang script can be named anything, and the executable
        # bit is what makes `open` run a plain file rather than display it.
        if is_file and (mode & stat.S_IXUSR):
            return (
                f"ERROR: refusing to open {p.name}: it is marked executable "
                "and would be run, not displayed."
            )
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
