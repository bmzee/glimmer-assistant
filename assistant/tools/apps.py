from __future__ import annotations

from pathlib import Path

from assistant.security.paths import PathNotAllowedError, resolve_safe
from assistant.tools.adapters.base import PlatformAdapter
from assistant.tools.registry import RiskTier, Tool


def make_app_tools(adapter: PlatformAdapter, allowed_roots: list[Path]) -> list[Tool]:
    def open_app(args: dict) -> str:
        return adapter.launch_app(args["name"])

    def open_path(args: dict) -> str:
        try:
            p = resolve_safe(args["path"], allowed_roots)
        except PathNotAllowedError as e:
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
            description="Open a file or folder with its default application.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            risk_tier=RiskTier.UNDO,
            platforms=("darwin", "win32"),
            func=open_path,
        ),
    ]
