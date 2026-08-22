from __future__ import annotations

from typing import Callable

from assistant.security.confirm import ConfirmRequest, build_confirm_request
from assistant.security.log import ActionLog
from assistant.tools.registry import RiskTier, Tool


class PermissionGate:
    def __init__(self, log: ActionLog, confirmer: Callable[[ConfirmRequest], bool]):
        self._log = log
        self._confirmer = confirmer

    def check(self, tool: Tool, args: dict) -> bool:
        tier = tool.risk_tier
        if tier == RiskTier.NEVER:
            self._record(tool, args, "refused")
            return False
        if tier == RiskTier.CONFIRM:
            request = build_confirm_request(tool.name, args)
            allowed = self._confirmer(request)
            self._record(tool, args, "confirmed" if allowed else "denied")
            return allowed
        self._record(tool, args, "auto")
        return True

    def _record(self, tool: Tool, args: dict, decision: str) -> None:
        self._log.append(
            {"tool": tool.name, "args": args, "tier": int(tool.risk_tier), "decision": decision}
        )
