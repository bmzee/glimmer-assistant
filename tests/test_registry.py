import pytest

from assistant.tools.registry import RiskTier, Tool, ToolRegistry


def make_tool(name: str, platforms: tuple[str, ...] = ("darwin", "win32")) -> Tool:
    return Tool(
        name=name,
        description=f"{name} description",
        parameters={"type": "object", "properties": {}, "required": []},
        risk_tier=RiskTier.AUTO,
        platforms=platforms,
        func=lambda args: "ok",
    )


def test_register_and_get():
    reg = ToolRegistry()
    reg.register(make_tool("list_dir"))
    assert reg.get("list_dir").name == "list_dir"
    assert reg.get("missing") is None


def test_duplicate_name_rejected():
    reg = ToolRegistry()
    reg.register(make_tool("list_dir"))
    with pytest.raises(ValueError):
        reg.register(make_tool("list_dir"))


def test_platform_filtering():
    reg = ToolRegistry()
    reg.register(make_tool("everywhere"))
    reg.register(make_tool("mac_only", platforms=("darwin",)))
    assert {t.name for t in reg.available("darwin")} == {"everywhere", "mac_only"}
    assert {t.name for t in reg.available("win32")} == {"everywhere"}


def test_openai_schema_shape():
    reg = ToolRegistry()
    reg.register(make_tool("list_dir"))
    (schema,) = reg.schemas("darwin")
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "list_dir"
    assert schema["function"]["parameters"]["type"] == "object"


def test_tool_untrusted_defaults_false():
    assert make_tool("x").untrusted is False
