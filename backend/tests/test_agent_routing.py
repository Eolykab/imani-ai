from app.agent.agent import PiPilotAgent


def test_explicit_task_instruction_routes_to_create_task():
    decision = PiPilotAgent()._safe_fallback("Add rehearse presentation to my tasks")
    assert decision.action == "tool"
    assert decision.tool is not None
    assert decision.tool.name == "create_task"
    assert decision.tool.arguments == {"text": "rehearse presentation"}


def test_task_due_date_is_structured():
    decision = PiPilotAgent()._safe_fallback("Add rehearse presentation due tomorrow at 9 to my tasks")
    assert decision.tool is not None
    assert decision.tool.arguments == {"text": "rehearse presentation", "due_date": "tomorrow at 9"}


def test_explicit_memory_instruction_routes_to_create_memory():
    decision = PiPilotAgent()._safe_fallback("Remember that the demo starts at 10 AM")
    assert decision.action == "tool"
    assert decision.tool is not None
    assert decision.tool.name == "create_memory"


def test_general_knowledge_question_uses_direct_ai_path():
    decision = PiPilotAgent()._safe_fallback("Why is the sky blue?")
    assert decision.action == "direct"
    assert decision.tool is None


def test_explicit_task_update_and_delete_routes():
    rename = PiPilotAgent()._safe_fallback("Rename task rehearse presentation to rehearse PiPilot demo")
    assert rename.tool is not None and rename.tool.name == "update_task"
    delete = PiPilotAgent()._safe_fallback("Delete task rehearse PiPilot demo")
    assert delete.tool is not None and delete.tool.name == "delete_task"


def test_explicit_reminder_routes_to_scheduler_tool():
    decision = PiPilotAgent()._safe_fallback("Remind me tomorrow at 9 to rehearse my presentation")
    assert decision.tool is not None and decision.tool.name == "create_reminder"
    assert decision.tool.arguments["when"] == "tomorrow at 9"
