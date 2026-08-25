import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Memory, Task
from app.services import system
from app.services.hailo import hailo_status
from app.services.ollama import OllamaService


class EmptyArgs(BaseModel):
    pass


class ProcessArgs(BaseModel):
    limit: int = Field(default=5, ge=1, le=20)


class TextArgs(BaseModel):
    text: str = Field(min_length=1, max_length=5000)


class SearchArgs(BaseModel):
    query: str = Field(default="", max_length=500)


class CompleteTaskArgs(BaseModel):
    query: str = Field(min_length=1, max_length=300)


class ServiceArgs(BaseModel):
    service: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_.@-]+$")


ToolHandler = Callable[[BaseModel, Session], Awaitable[Any]]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    schema: type[BaseModel]
    handler: ToolHandler


async def _sync(function: Callable[..., Any], *args: Any) -> Any:
    return await asyncio.to_thread(function, *args)


async def _system(function: Callable[[], Any], _args: BaseModel, _db: Session) -> Any:
    return await _sync(function)


async def memories_create(args: BaseModel, db: Session) -> Any:
    assert isinstance(args, TextArgs)
    row = Memory(content=args.text)
    db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id, "content": row.content, "created_at": row.created_at.isoformat()}


async def memories_list(args: BaseModel, db: Session) -> Any:
    assert isinstance(args, SearchArgs)
    statement = select(Memory).order_by(Memory.created_at.desc()).limit(100)
    if args.query:
        statement = statement.where(Memory.content.ilike(f"%{args.query}%"))
    return [{"id": row.id, "content": row.content, "created_at": row.created_at.isoformat()} for row in db.scalars(statement)]


async def tasks_create(args: BaseModel, db: Session) -> Any:
    assert isinstance(args, TextArgs)
    row = Task(title=args.text)
    db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id, "title": row.title, "status": row.status}


async def tasks_list(_args: BaseModel, db: Session) -> Any:
    rows = db.scalars(select(Task).order_by(Task.created_at.desc()).limit(100))
    return [{"id": row.id, "title": row.title, "status": row.status} for row in rows]


async def tasks_complete(args: BaseModel, db: Session) -> Any:
    assert isinstance(args, CompleteTaskArgs)
    from datetime import datetime, timezone
    row = db.scalar(select(Task).where(Task.title.ilike(f"%{args.query}%"), Task.status == "pending").limit(1))
    if not row:
        return {"updated": False, "message": "No matching pending task"}
    row.status = "completed"; row.completed_at = datetime.now(timezone.utc); db.commit()
    return {"updated": True, "id": row.id, "title": row.title}


async def ollama_check(_args: BaseModel, _db: Session) -> Any:
    return await OllamaService().status()


async def service_check(args: BaseModel, _db: Session) -> Any:
    assert isinstance(args, ServiceArgs)
    allowed = get_settings().pipilot_allowed_services
    if args.service not in allowed:
        return {"allowed": False, "status": "rejected", "message": "Service is not approved"}
    if not __import__("shutil").which("systemctl"):
        return {"allowed": True, "status": "unavailable", "message": "Unavailable in development environment"}
    process = await asyncio.create_subprocess_exec("systemctl", "is-active", args.service, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, _ = await asyncio.wait_for(process.communicate(), timeout=5)
    return {"allowed": True, "service": args.service, "status": stdout.decode().strip() or "unknown"}


async def restart_approved_service(service: str) -> dict[str, Any]:
    """Restart a prevalidated service. This is intentionally not registered for LLM use."""
    if service not in get_settings().pipilot_allowed_services:
        return {"executed": False, "status": "rejected", "message": "Service is not approved"}
    if not __import__("shutil").which("systemctl"):
        return {"executed": False, "status": "unavailable", "message": "Unavailable in development environment"}
    process = await asyncio.create_subprocess_exec(
        "systemctl", "restart", service, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await asyncio.wait_for(process.communicate(), timeout=20)
    return {"executed": process.returncode == 0, "service": service,
            "status": "restarted" if process.returncode == 0 else "failed",
            "message": stderr.decode(errors="replace").strip()[:300]}


TOOLS: dict[str, ToolDefinition] = {}


def register(name: str, description: str, schema: type[BaseModel], handler: ToolHandler) -> None:
    TOOLS[name] = ToolDefinition(name, description, schema, handler)


def _system_handler(function: Callable[[], Any]) -> ToolHandler:
    async def handler(args: BaseModel, db: Session) -> Any:
        return await _system(function, args, db)
    return handler


for name, description, function in [
    ("cpu_usage", "Current CPU utilization", system.cpu_usage), ("cpu_load", "CPU load averages", system.cpu_load),
    ("cpu_temperature", "CPU temperature", system.cpu_temperature), ("ram_usage", "RAM usage and available memory", system.ram_usage),
    ("disk_usage", "Root disk usage", system.disk_usage), ("uptime", "System uptime", system.uptime),
    ("hostname", "Device hostname", system.hostname), ("os_information", "Operating system information", system.os_information),
    ("raspberry_pi_model", "Raspberry Pi model", system.raspberry_pi_model), ("network_information", "Local IP and network interfaces", system.network_information),
    ("system_health", "Comprehensive live device health report", system.system_health),
]: register(name, description, EmptyArgs, _system_handler(function))

register("top_cpu_processes", "Processes using the most CPU", ProcessArgs, lambda a, d: _sync(system.top_processes, "cpu", a.limit))
register("top_memory_processes", "Processes using the most memory", ProcessArgs, lambda a, d: _sync(system.top_processes, "memory", a.limit))
register("ollama_status", "Ollama reachability and configured Qwen model availability", EmptyArgs, ollama_check)
register("hailo_status", "Hailo accelerator detection; it does not accelerate Ollama", EmptyArgs, lambda a, d: hailo_status())
register("create_memory", "Save a memory or note", TextArgs, memories_create)
register("list_memories", "List or search saved memories", SearchArgs, memories_list)
register("create_task", "Add a task", TextArgs, tasks_create)
register("list_tasks", "List tasks", EmptyArgs, tasks_list)
register("complete_task", "Mark a matching task completed", CompleteTaskArgs, tasks_complete)
register("service_status", "Check an explicitly approved system service", ServiceArgs, service_check)


def tool_catalog() -> list[dict[str, Any]]:
    return [{"name": tool.name, "description": tool.description, "parameters": tool.schema.model_json_schema()} for tool in TOOLS.values()]


async def execute_tool(name: str, arguments: dict[str, Any], db: Session) -> Any:
    tool = TOOLS.get(name)
    if tool is None:
        raise ValueError("Unknown or unapproved tool")
    try:
        validated = tool.schema.model_validate(arguments)
    except ValidationError as exc:
        raise ValueError("Invalid tool arguments") from exc
    return await tool.handler(validated, db)
