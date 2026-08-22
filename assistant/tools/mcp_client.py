from __future__ import annotations

import re
from dataclasses import dataclass

from assistant.security.confirm import sanitize_preview
from assistant.tools.registry import RiskTier, Tool

# OpenAI function-name grammar. A descriptor violating this makes a strict
# endpoint 400 the ENTIRE request every turn for the whole session, so a
# hostile/broken MCP server must not be able to register a tool that breaks it.
_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_DESCRIPTION_MAX_CHARS = 200


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


def _sanitize_description(text: str) -> str:
    """A hostile MCP server can inject instructions via `description` into the
    tool schema at registration time — this is metadata, not a tool RESULT, so
    the untrusted/SessionTrust machinery (which covers results) doesn't touch
    it. Strip control chars, collapse newlines/whitespace, and cap length."""
    clean = sanitize_preview(text)
    if len(clean) > _DESCRIPTION_MAX_CHARS:
        clean = clean[:_DESCRIPTION_MAX_CHARS].rstrip() + "..."
    return clean


def _wrap(spec: MCPServerSpec, session, descriptor: dict) -> Tool:
    remote_name = descriptor.get("name")
    if not remote_name:
        raise ValueError("descriptor missing or empty 'name' field")
    if not _NAME_RE.match(remote_name):
        raise ValueError(f"descriptor 'name' violates function-name grammar: {remote_name!r}")

    namespaced_name = f"{spec.name}__{remote_name}"
    if not _NAME_RE.match(namespaced_name):
        raise ValueError(
            f"namespaced tool name violates function-name grammar: {namespaced_name!r}"
        )

    description = _sanitize_description(
        descriptor.get("description", f"{spec.name} {remote_name}")
    )

    def call(args: dict) -> str:
        try:
            return str(session.call_tool(remote_name, args))
        except Exception as e:
            return f"ERROR: {e}"

    return Tool(
        name=namespaced_name,
        description=description,
        parameters=descriptor.get(
            "inputSchema", {"type": "object", "properties": {}, "required": []}
        ),
        risk_tier=spec.risk_tier,
        platforms=("darwin", "win32"),
        func=call,
        untrusted=spec.untrusted,
        outbound=spec.outbound,
    )
