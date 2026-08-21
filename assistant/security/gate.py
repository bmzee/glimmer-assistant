from __future__ import annotations

from typing import Callable

from assistant.security.log import ActionLog
from assistant.tools.registry import RiskTier, Tool


class PermissionGate:
    def __init__(self, log: ActionLog, confirmer: Callable[[str], bool]):
        self._log = log
        self._confirmer = confirmer

    def check(self, tool: Tool, args: dict) -> bool:
        tier = tool.risk_tier
        if tier == RiskTier.NEVER:
            self._record(tool, args, "refused")
            return False
        if tier == RiskTier.CONFIRM:
            allowed = self._confirmer(f"{tool.name}({args})")
            self._record(tool, args, "confirmed" if allowed else "denied")
            return allowed
        self._record(tool, args, "auto")
        return True

    def _record(self, tool: Tool, args: dict, decision: str) -> None:
        self._log.append(
            {"tool": tool.name, "args": args, "tier": int(tool.risk_tier), "decision": decision}
        )
