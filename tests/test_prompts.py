from assistant.agent.prompts import SYSTEM_PROMPT


def test_prompt_tells_model_to_decline_when_no_tool_fits():
    text = SYSTEM_PROMPT.lower()
    assert "no tool" in text
    assert "stop" in text or "say so" in text
