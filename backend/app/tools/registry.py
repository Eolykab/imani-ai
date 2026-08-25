import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Memory, Reminder, Task
from app.services import system
from app.services.hailo import hailo_status
from app.services.ollama import OllamaService
from app.services.reminders import display_local, parse_reminder_time
from app.services.weather import current_weather


class EmptyArgs(BaseModel):
    pass


class ProcessArgs(BaseModel):
    limit: int = Field(default=5, ge=1, le=20)


class TextArgs(BaseModel):
    text: str = Field(min_length=1, max_length=5000)


class CreateTaskArgs(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=300)
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=5000)
    due_date: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def require_title(self) -> "CreateTaskArgs":
        if not (self.title or self.text): raise ValueError("title or text is required")
        return self


class SearchArgs(BaseModel):
    query: str = Field(default="", max_length=500)


class CompleteTaskArgs(BaseModel):
    query: str = Field(min_length=1, max_length=300)


class UpdateTaskArgs(BaseModel):
    query: str = Field(min_length=1, max_length=300)
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=5000)
    due_date: str | None = Field(default=None, max_length=80)
    status: str | None = Field(default=None, pattern="^(pending|completed|cancelled)$")


class DeleteTaskArgs(BaseModel):
    query: str = Field(min_length=1, max_length=300)


class ReminderArgs(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    when: str = Field(min_length=1, max_length=100)
    recurrence: str | None = Field(default=None, pattern="^(daily|weekly)$")


class DeleteByIdArgs(BaseModel):
    id: int = Field(gt=0)


class ServiceArgs(BaseModel):
    service: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_.@-]+$")


ToolHandler = Callable[[BaseModel, Session], Awaitable[Any]]


def _owner(db: Session) -> str:
    return str(db.info.get("owner_id", "shared"))


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
    row = Memory(content=args.text, owner_id=_owner(db))
    db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id, "content": row.content, "created_at": row.created_at.isoformat()}


async def memories_list(args: BaseModel, db: Session) -> Any:
    assert isinstance(args, SearchArgs)
    statement = select(Memory).where(Memory.owner_id.in_([_owner(db), "shared"])).order_by(Memory.created_at.desc()).limit(100)
    if args.query:
        statement = statement.where(Memory.content.ilike(f"%{args.query}%"))
    return [{"id": row.id, "content": row.content, "created_at": row.created_at.isoformat()} for row in db.scalars(statement)]


async def tasks_create(args: BaseModel, db: Session) -> Any:
    assert isinstance(args, CreateTaskArgs)
    due_date = None
    if args.due_date:
        try: due_date = parse_reminder_time(args.due_date)
        except ValueError as exc: return {"created": False, "message": str(exc)}
    row = Task(title=args.title or args.text or "Untitled", description=args.description, due_date=due_date, owner_id=_owner(db))
    db.add(row); db.commit(); db.refresh(row)
    return {"created": True, "id": row.id, "title": row.title, "description": row.description,
            "due_date": display_local(row.due_date) if row.due_date else None, "status": row.status}


async def tasks_list(_args: BaseModel, db: Session) -> Any:
    rows = db.scalars(select(Task).where(Task.owner_id.in_([_owner(db), "shared"])).order_by(Task.created_at.desc()).limit(100))
    return [{"id": row.id, "title": row.title, "status": row.status} for row in rows]


async def tasks_complete(args: BaseModel, db: Session) -> Any:
    assert isinstance(args, CompleteTaskArgs)
    from datetime import datetime, timezone
    row = db.scalar(select(Task).where(Task.owner_id.in_([_owner(db), "shared"]), Task.title.ilike(f"%{args.query}%"), Task.status == "pending").limit(1))
    if not row:
        return {"updated": False, "message": "No matching pending task"}
    row.status = "completed"; row.completed_at = datetime.now(timezone.utc); db.commit()
    return {"updated": True, "id": row.id, "title": row.title}


def _find_task(db: Session, query: str) -> Task | None:
    if query.isdigit():
        row = db.get(Task, int(query))
        return row if row and row.owner_id in {_owner(db), "shared"} else None
    return db.scalar(select(Task).where(Task.owner_id.in_([_owner(db), "shared"]), Task.title.ilike(f"%{query}%")).order_by(Task.created_at.desc()).limit(1))


async def tasks_update(args: BaseModel, db: Session) -> Any:
    assert isinstance(args, UpdateTaskArgs)
    from datetime import datetime, timezone
    row = _find_task(db, args.query)
    if not row:
        return {"updated": False, "message": "No matching task"}
    changes = args.model_dump(exclude={"query"}, exclude_none=True)
    if "due_date" in changes:
        try:
            changes["due_date"] = datetime.fromisoformat(changes["due_date"].replace("Z", "+00:00"))
        except ValueError:
            return {"updated": False, "message": "Due date must use ISO 8601 format"}
    for key, value in changes.items():
        setattr(row, key, value)
    if changes.get("status") == "completed" and not row.completed_at:
        row.completed_at = datetime.now(timezone.utc)
    elif "status" in changes and changes["status"] != "completed":
        row.completed_at = None
    db.commit(); db.refresh(row)
    return {"updated": True, "id": row.id, "title": row.title, "description": row.description,
            "status": row.status, "due_date": row.due_date.isoformat() if row.due_date else None}


async def tasks_delete(args: BaseModel, db: Session) -> Any:
    assert isinstance(args, DeleteTaskArgs)
    row = _find_task(db, args.query)
    if not row:
        return {"deleted": False, "message": "No matching task"}
    result = {"deleted": True, "id": row.id, "title": row.title}
    db.delete(row); db.commit()
    return result


async def reminders_create(args: BaseModel, db: Session) -> Any:
    assert isinstance(args, ReminderArgs)
    try: remind_at = parse_reminder_time(args.when)
    except ValueError as exc: return {"created": False, "message": str(exc)}
    row = Reminder(owner_id=_owner(db), title=args.text, remind_at=remind_at, recurrence=args.recurrence)
    db.add(row); db.commit(); db.refresh(row)
    return {"created": True, "id": row.id, "text": row.title, "when": display_local(row.remind_at), "recurrence": row.recurrence}


async def reminders_list(_args: BaseModel, db: Session) -> Any:
    rows = db.scalars(select(Reminder).where(Reminder.owner_id == _owner(db), Reminder.status == "pending").order_by(Reminder.remind_at))
    return [{"id": row.id, "text": row.title, "when": display_local(row.remind_at), "recurrence": row.recurrence} for row in rows]


async def reminders_delete(args: BaseModel, db: Session) -> Any:
    assert isinstance(args, DeleteByIdArgs)
    row = db.get(Reminder, args.id)
    if not row or row.owner_id != _owner(db): return {"deleted": False, "message": "Reminder not found"}
    row.status = "cancelled"; db.commit(); return {"deleted": True, "id": row.id}


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
register("create_task", "Add a task with optional description and due date", CreateTaskArgs, tasks_create)
register("list_tasks", "List tasks", EmptyArgs, tasks_list)
register("complete_task", "Mark a matching task completed", CompleteTaskArgs, tasks_complete)
register("update_task", "Edit a task title, description, due date, or status by ID or title", UpdateTaskArgs, tasks_update)
register("delete_task", "Delete a task by ID or matching title", DeleteTaskArgs, tasks_delete)
register("create_reminder", "Schedule a reminder; when supports relative time or ISO date", ReminderArgs, reminders_create)
register("list_reminders", "List scheduled reminders", EmptyArgs, reminders_list)
register("delete_reminder", "Cancel a reminder by numeric ID", DeleteByIdArgs, reminders_delete)
register("current_weather", "Get real current weather for the configured location using the internet", EmptyArgs, lambda a, d: current_weather())
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
