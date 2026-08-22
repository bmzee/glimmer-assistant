from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Callable


class RiskTier(IntEnum):
    AUTO = 0     # read-only: runs freely
    UNDO = 1     # low-blast-radius mutation: runs, logged, undoable (undo UX in Plan 2)
    CONFIRM = 2  # blocking confirmation with preview
    NEVER = 3    # hard-coded refusal (spec §8.3 tier 3)


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict  # JSON Schema for the arguments object
    risk_tier: RiskTier
    platforms: tuple[str, ...]  # sys.platform values: "darwin", "win32"
    func: Callable[[dict], str]
    untrusted: bool = False
    outbound: bool = False


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool: {tool.name}")
        self._tools[tool.name] = tool

    def available(self, platform: str) -> list[Tool]:
        return [t for t in self._tools.values() if platform in t.platforms]

    def schemas(self, platform: str) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self.available(platform)
        ]

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)
