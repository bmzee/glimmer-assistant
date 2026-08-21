from __future__ import annotations

from pathlib import Path

from assistant.security.paths import resolve_safe
from assistant.tools.registry import RiskTier, Tool

_PATH_PARAM = {
    "type": "object",
    "properties": {"path": {"type": "string"}},
    "required": ["path"],
}


def make_files_tools(allowed_roots: list[Path]) -> list[Tool]:
    def list_dir(args: dict) -> str:
        p = resolve_safe(args["path"], allowed_roots)
        entries = sorted(e.name + ("/" if e.is_dir() else "") for e in p.iterdir())
        return "\n".join(entries) or "(empty)"

    def read_file(args: dict) -> str:
        p = resolve_safe(args["path"], allowed_roots)
        return p.read_text(errors="replace")

    return [
        Tool(
            name="list_dir",
            description="List the entries in a directory. Directories end with '/'.",
            parameters=_PATH_PARAM,
            risk_tier=RiskTier.AUTO,
            platforms=("darwin", "win32"),
            func=list_dir,
        ),
        Tool(
            name="read_file",
            description="Read a text file's contents.",
            parameters=_PATH_PARAM,
            risk_tier=RiskTier.AUTO,
            platforms=("darwin", "win32"),
            func=read_file,
        ),
    ]
