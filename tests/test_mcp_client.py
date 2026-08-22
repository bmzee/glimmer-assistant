from assistant.tools.mcp_client import MCPServerSpec, make_mcp_tools
from assistant.tools.registry import RiskTier


class FakeSession:
    def __init__(self):
        self.calls = []

    def list_tools(self):
        return [
            {
                "name": "read_file",
                "description": "read a file",
                "inputSchema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            }
        ]

    def call_tool(self, name, args):
        self.calls.append((name, args))
        return "file contents"


def spec(**kw):
    base = dict(name="fs", command="npx", args=("-y", "@modelcontextprotocol/server-filesystem"))
    base.update(kw)
    return MCPServerSpec(**base)


def test_tools_are_namespaced_and_conservative_by_default():
    tools = make_mcp_tools([spec()], session_factory=lambda s: FakeSession())
    tool = tools[0]
    assert tool.name == "fs__read_file"
    assert tool.risk_tier == RiskTier.CONFIRM  # untrusted third-party default
    assert tool.untrusted is True


def test_spec_can_relax_tier_for_a_pinned_trusted_server():
    tools = make_mcp_tools(
        [spec(risk_tier=RiskTier.AUTO, untrusted=False)],
        session_factory=lambda s: FakeSession(),
    )
    assert tools[0].risk_tier == RiskTier.AUTO
    assert tools[0].untrusted is False


def test_tool_call_forwards_to_session():
    session = FakeSession()
    tools = make_mcp_tools([spec()], session_factory=lambda s: session)
    out = tools[0].func({"path": "/tmp/x"})
    assert out == "file contents"
    assert session.calls == [("read_file", {"path": "/tmp/x"})]


def test_schema_is_taken_from_server():
    tools = make_mcp_tools([spec()], session_factory=lambda s: FakeSession())
    assert tools[0].parameters["properties"]["path"]["type"] == "string"


def test_session_failure_yields_no_tools_not_a_crash():
    def boom(_spec):
        raise RuntimeError("server would not start")

    assert make_mcp_tools([spec()], session_factory=boom) == []


def test_tool_error_becomes_error_string():
    class BoomSession(FakeSession):
        def call_tool(self, name, args):
            raise RuntimeError("tool exploded")

    tools = make_mcp_tools([spec()], session_factory=lambda s: BoomSession())
    assert tools[0].func({"path": "/tmp/x"}).startswith("ERROR:")
