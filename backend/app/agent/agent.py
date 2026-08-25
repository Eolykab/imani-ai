import json
import logging
import re
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.services.activity import record_activity
from app.services.ollama import OllamaService
from app.tools import execute_tool, tool_catalog

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are PiPilot, a private, helpful general-purpose AI assistant running on a Raspberry Pi.
Answer general-knowledge questions, explain concepts, help with writing, brainstorming, learning, planning,
math, programming, and everyday questions using the local Qwen model. You also have explicitly approved
tools for live Raspberry Pi information, memories, tasks, Ollama, and Hailo. Use tools only when the request
needs them. Your built-in knowledge may be outdated: never pretend to have browsed the web or verified
current news, prices, weather, laws, schedules, or other changing facts. Say when current verification is
needed. Never claim Hailo accelerates Ollama. Never invent system metric values. Be concise, useful, and
transparent when a capability is unavailable. Never reveal secrets, environment variables, credentials,
arbitrary files, or internal reasoning."""


class ToolCall(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class Decision(BaseModel):
    action: str = Field(pattern="^(direct|tool)$")
    tool: ToolCall | None = None


class AgentResult(BaseModel):
    response: str
    tools_used: list[str] = []


class PiPilotAgent:
    def __init__(self) -> None:
        self.ollama = OllamaService()

    async def _select(self, message: str) -> Decision:
        catalog = json.dumps(tool_catalog(), separators=(",", ":"))
        prompt = f"""Choose whether to answer directly or call exactly one tool.
Return JSON only: {{"action":"direct"}} or {{"action":"tool","tool":{{"name":"...","arguments":{{}}}}}}.
Use semantic intent, not simple keyword matching. Available tools: {catalog}\nUser: {message}"""
        content = await self.ollama.chat([{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}], format_json=True)
        return Decision.model_validate_json(content)

    def _safe_fallback(self, message: str) -> Decision:
        lower = message.lower().strip()
        patterns: list[tuple[str, str]] = [
            (r"\b(health report|system health|pi health)\b", "system_health"), (r"\btemperature\b", "cpu_temperature"),
            (r"\b(ram|memory available|memory usage)\b", "ram_usage"), (r"\b(ip address|network)\b", "network_information"),
            (r"\b(uptime|how long.*running)\b", "uptime"), (r"\bollama\b", "ollama_status"),
            (r"\b(hailo|accelerator)\b", "hailo_status"), (r"\btop.*memory|most memory\b", "top_memory_processes"),
            (r"\btop.*cpu|most cpu\b", "top_cpu_processes"), (r"\b(show|list|what).*(notes|memories|remember)\b", "list_memories"),
            (r"\b(show|list).*(tasks|to.?do)\b", "list_tasks"),
        ]
        remember = re.match(r"(?:please\s+)?(?:remember(?: that)?|save a note(?: that)?)\s+(.+)", lower, re.I)
        if remember:
            return Decision(action="tool", tool=ToolCall(name="create_memory", arguments={"text": remember.group(1)}))
        task = re.match(r"(?:please\s+)?(?:add|create)\s+(.+?)(?:\s+to my tasks?|\s+as a task)$", lower, re.I)
        if task:
            return Decision(action="tool", tool=ToolCall(name="create_task", arguments={"text": task.group(1)}))
        complete = re.match(r"(?:mark|complete)\s+(.+?)(?:\s+as done|\s+done)?$", lower, re.I)
        if complete:
            return Decision(action="tool", tool=ToolCall(name="complete_task", arguments={"query": complete.group(1)}))
        for pattern, tool in patterns:
            if re.search(pattern, lower):
                return Decision(action="tool", tool=ToolCall(name=tool, arguments={}))
        return Decision(action="direct")

    async def run(self, message: str, history: list[dict[str, str]], db: Session, source: str = "web") -> AgentResult:
        record_activity(db, source, "ai_request", "Request received")
        # Route clear operational requests deterministically so the model cannot
        # claim a task or memory was saved without executing the validated tool.
        # Ambiguous language still goes to Qwen for semantic tool selection.
        decision = self._safe_fallback(message)
        if decision.action == "direct":
            try:
                decision = await self._select(message)
            except (httpx.HTTPError, ValueError, ValidationError, KeyError):
                decision = Decision(action="direct")
        if decision.action == "tool" and decision.tool:
            try:
                record_activity(db, "agent", "tool_selected", decision.tool.name)
                result = await execute_tool(decision.tool.name, decision.tool.arguments, db)
                record_activity(db, "tool", "tool_executed", decision.tool.name)
            except ValueError:
                logger.warning("Rejected invalid tool request: %s", decision.tool.name)
                return AgentResult(response="I rejected an invalid or unapproved tool request.")
            explanation_prompt = f"User request: {message}\nApproved tool: {decision.tool.name}\nReal tool result: {json.dumps(result, default=str)}\nExplain this result accurately and concisely. Never invent values."
            try:
                text = await self.ollama.chat([{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": explanation_prompt}])
            except httpx.HTTPError:
                text = self._format_tool_result(decision.tool.name, result)
            return AgentResult(response=text, tools_used=[decision.tool.name])
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, *history[-20:], {"role": "user", "content": message}]
        try:
            return AgentResult(response=await self.ollama.chat(messages))
        except httpx.HTTPError:
            return AgentResult(response="Ollama is currently unavailable. System tools, notes, and tasks can still be used.")

    @staticmethod
    def _format_tool_result(name: str, result: Any) -> str:
        return f"{name.replace('_', ' ').title()}:\n```json\n{json.dumps(result, indent=2, default=str)}\n```"
