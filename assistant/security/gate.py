from __future__ import annotations

from typing import Callable

from assistant.security.confirm import ConfirmRequest, build_confirm_request
from assistant.security.log import ActionLog
from assistant.security.trust import SessionTrust
from assistant.tools.registry import RiskTier, Tool


class PermissionGate:
    def __init__(
        self,
        log: ActionLog,
        confirmer: Callable[[ConfirmRequest], bool],
        trust: SessionTrust | None = None,
    ):
        self._log = log
        self._confirmer = confirmer
        self._trust = trust

    def check(self, tool: Tool, args: dict) -> bool:
        tier = tool.risk_tier
        if tier == RiskTier.NEVER:
            self._record(tool, args, "refused")
            return False

        elevated = (
            tool.outbound
            and self._trust is not None
            and self._trust.has_ingested_untrusted()
        )
        if tier == RiskTier.CONFIRM or elevated:
            request = build_confirm_request(
                tool.name,
                args,
                elevated=elevated,
                trust_sources=self._trust.sources() if self._trust else (),
            )
            allowed = self._confirmer(request)
            self._record(
                tool, args, "confirmed" if allowed else "denied", elevated=elevated
            )
            return allowed

        self._record(tool, args, "auto")
        return True

    def _record(self, tool: Tool, args: dict, decision: str, elevated: bool = False) -> None:
        record = {
            "tool": tool.name,
            "args": args,
            "tier": int(tool.risk_tier),
            "decision": decision,
        }
        if elevated:
            record["elevated"] = True
        self._log.append(record)
