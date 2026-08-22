from __future__ import annotations

from dataclasses import dataclass

from assistant.tools.registry import RiskTier, Tool


@dataclass(frozen=True)
class MCPServerSpec:
    """A pinned MCP server. Defaults are deliberately conservative: a
    third-party server's tools are CONFIRM-tier and untrusted unless the
    operator explicitly relaxes them for an audited server."""

    name: str
    command: str
    args: tuple[str, ...] = ()
    risk_tier: RiskTier = RiskTier.CONFIRM
    untrusted: bool = True
    outbound: bool = False


def _default_session_factory(spec: MCPServerSpec):
    raise RuntimeError(
        "no MCP session factory configured; pass session_factory= to connect"
    )


def make_mcp_tools(specs, *, session_factory=None) -> list[Tool]:
    factory = session_factory or _default_session_factory
    tools: list[Tool] = []
    for spec in specs:
        try:
            session = factory(spec)
            listed = session.list_tools()
        except Exception:
            continue  # a broken server must not break the assistant
        for descriptor in listed:
            try:
                tools.append(_wrap(spec, session, descriptor))
            except Exception:
                continue  # a malformed descriptor must not drop other tools/servers
    return tools


def _wrap(spec: MCPServerSpec, session, descriptor: dict) -> Tool:
    remote_name = descriptor.get("name")
    if not remote_name:
        raise ValueError("descriptor missing or empty 'name' field")

    def call(args: dict) -> str:
        try:
            return str(session.call_tool(remote_name, args))
        except Exception as e:
            return f"ERROR: {e}"

    return Tool(
        name=f"{spec.name}__{remote_name}",
        description=descriptor.get("description", f"{spec.name} {remote_name}"),
        parameters=descriptor.get(
            "inputSchema", {"type": "object", "properties": {}, "required": []}
        ),
        risk_tier=spec.risk_tier,
        platforms=("darwin", "win32"),
        func=call,
        untrusted=spec.untrusted,
        outbound=spec.outbound,
    )
