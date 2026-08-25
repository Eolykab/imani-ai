from app.agent.agent import PiPilotAgent


def test_explicit_task_instruction_routes_to_create_task():
    decision = PiPilotAgent()._safe_fallback("Add rehearse presentation to my tasks")
    assert decision.action == "tool"
    assert decision.tool is not None
    assert decision.tool.name == "create_task"
    assert decision.tool.arguments == {"text": "rehearse presentation"}


def test_explicit_memory_instruction_routes_to_create_memory():
    decision = PiPilotAgent()._safe_fallback("Remember that the demo starts at 10 AM")
    assert decision.action == "tool"
    assert decision.tool is not None
    assert decision.tool.name == "create_memory"


def test_general_knowledge_question_uses_direct_ai_path():
    decision = PiPilotAgent()._safe_fallback("Why is the sky blue?")
    assert decision.action == "direct"
    assert decision.tool is None
