from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent import PiPilotAgent
from app.core.config import get_settings
from app.db.session import get_db
from app.models import Activity, ChatRecord, Memory, Reminder, Task, UploadedFile, VoiceTranscript
from app.schemas.api import ChatRequest, ChatResponse, FileQuestion, MemoryCreate, MemoryOut, ReminderCreate, TaskCreate, TaskOut, TaskUpdate
from app.services import system
from app.services.activity import record_activity
from app.services.files import read_controlled_file, save_upload
from app.services.hailo import hailo_status
from app.services.ollama import OllamaService
from app.services.reminders import display_local, parse_reminder_time

router = APIRouter(prefix="/api")
Db = Annotated[Session, Depends(get_db)]


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "PiPilot"}


@router.get("/system")
def get_system(db: Db) -> dict:
    record_activity(db, "web", "health_check", "System metrics requested")
    return system.system_health()


@router.get("/system/processes")
def processes(sort: str = Query("memory", pattern="^(cpu|memory)$")) -> list[dict]:
    return system.top_processes(sort)


@router.get("/ollama/status")
async def ollama_status() -> dict:
    return await OllamaService().status()


@router.get("/hailo/status")
async def get_hailo_status() -> dict:
    return await hailo_status()


@router.get("/status")
async def status() -> dict:
    settings = get_settings()
    metrics = system.system_health()
    ollama, hailo = await OllamaService().status(), await hailo_status()
    return {"system": metrics, "ollama": ollama, "hailo": hailo,
            "telegram": {"configured": bool(settings.telegram_bot_token), "allowed_users": len(settings.telegram_allowed_user_ids)},
            "local_ai": True}


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, db: Db) -> ChatResponse:
    db.add(ChatRecord(owner_id="web", source="web", role="user", content=payload.message)); db.commit()
    result = await PiPilotAgent().run(payload.message, [row.model_dump() for row in payload.history], db, "web", "web")
    db.add(ChatRecord(owner_id="web", source="web", role="assistant", content=result.response, tools_used=",".join(result.tools_used) or None)); db.commit()
    return ChatResponse(response=result.response, tools_used=result.tools_used)


@router.get("/chat/history")
def chat_history(db: Db, limit: int = Query(50, ge=1, le=200)) -> list[dict]:
    rows = list(db.scalars(select(ChatRecord).where(ChatRecord.owner_id == "web").order_by(ChatRecord.created_at.desc()).limit(limit)))
    return [{"id": row.id, "role": row.role, "content": row.content,
             "tools_used": row.tools_used.split(",") if row.tools_used else [], "created_at": row.created_at} for row in reversed(rows)]


@router.delete("/chat/history", status_code=204)
def clear_chat_history(db: Db) -> None:
    for row in db.scalars(select(ChatRecord).where(ChatRecord.owner_id == "web")):
        db.delete(row)
    db.commit()


@router.get("/memories", response_model=list[MemoryOut])
def memories(db: Db, q: str = "") -> list[Memory]:
    statement = select(Memory).order_by(Memory.created_at.desc())
    if q:
        statement = statement.where(Memory.content.ilike(f"%{q}%"))
    return list(db.scalars(statement))


@router.post("/memories", response_model=MemoryOut, status_code=201)
def create_memory(payload: MemoryCreate, db: Db) -> Memory:
    row = Memory(content=payload.content); db.add(row); db.commit(); db.refresh(row)
    record_activity(db, "web", "memory_created", f"Memory {row.id} created")
    return row


@router.delete("/memories/{memory_id}", status_code=204)
def delete_memory(memory_id: int, db: Db) -> None:
    row = db.get(Memory, memory_id)
    if not row: raise HTTPException(404, "Memory not found")
    db.delete(row); db.commit()


@router.get("/tasks", response_model=list[TaskOut])
def tasks(db: Db, status: str | None = None) -> list[Task]:
    statement = select(Task).order_by(Task.created_at.desc())
    if status: statement = statement.where(Task.status == status)
    return list(db.scalars(statement))


@router.post("/tasks", response_model=TaskOut, status_code=201)
def create_task(payload: TaskCreate, db: Db) -> Task:
    row = Task(**payload.model_dump()); db.add(row); db.commit(); db.refresh(row)
    record_activity(db, "web", "task_created", f"Task {row.id} created")
    return row


@router.patch("/tasks/{task_id}", response_model=TaskOut)
def update_task(task_id: int, payload: TaskUpdate, db: Db) -> Task:
    row = db.get(Task, task_id)
    if not row: raise HTTPException(404, "Task not found")
    for key, value in payload.model_dump(exclude_unset=True).items(): setattr(row, key, value)
    if payload.status == "completed" and not row.completed_at: row.completed_at = datetime.now(timezone.utc)
    if payload.status and payload.status != "completed": row.completed_at = None
    db.commit(); db.refresh(row); return row


@router.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: int, db: Db) -> None:
    row = db.get(Task, task_id)
    if not row: raise HTTPException(404, "Task not found")
    db.delete(row); db.commit()


@router.get("/files")
def files(db: Db) -> list[dict]:
    rows = db.scalars(select(UploadedFile).order_by(UploadedFile.created_at.desc()))
    return [{"id": r.id, "name": r.original_name, "size": r.size, "created_at": r.created_at} for r in rows]


@router.post("/files", status_code=201)
async def upload_file(file: Annotated[UploadFile, File()], db: Db) -> dict:
    try: original, stored, size = await save_upload(file)
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc
    row = UploadedFile(original_name=original, stored_name=stored, content_type=file.content_type, size=size, owner_id="web")
    db.add(row); db.commit(); db.refresh(row); record_activity(db, "web", "file_uploaded", f"File {row.id} uploaded")
    return {"id": row.id, "name": row.original_name, "size": row.size}


@router.post("/files/{file_id}/ask", response_model=ChatResponse)
async def ask_file(file_id: int, payload: FileQuestion, db: Db) -> ChatResponse:
    row = db.get(UploadedFile, file_id)
    if not row: raise HTTPException(404, "File not found")
    try: content = read_controlled_file(row.stored_name)
    except OSError as exc: raise HTTPException(404, "Stored file unavailable") from exc
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc
    prompt = f"File: {row.original_name}\nQuestion: {payload.question}\n\nContent:\n{content}"
    try:
        answer = await OllamaService().chat([{"role": "system", "content": "Answer using only the supplied local file. Say when the answer is not present."}, {"role": "user", "content": prompt}])
    except httpx.HTTPError as exc: raise HTTPException(503, "Ollama unavailable") from exc
    record_activity(db, "web", "file_question", f"File {row.id} queried")
    return ChatResponse(response=answer)


@router.delete("/files/{file_id}", status_code=204)
def delete_file(file_id: int, db: Db) -> None:
    row = db.get(UploadedFile, file_id)
    if not row: raise HTTPException(404, "File not found")
    path = (get_settings().pipilot_upload_dir / Path(row.stored_name).name)
    try: path.unlink(missing_ok=True)
    except OSError as exc: raise HTTPException(500, "Could not remove stored file") from exc
    db.delete(row); db.commit(); record_activity(db, "web", "file_deleted", f"File {file_id} deleted")


@router.get("/activity")
def activity(db: Db, limit: int = Query(50, ge=1, le=200)) -> list[dict]:
    rows = db.scalars(select(Activity).order_by(Activity.created_at.desc()).limit(limit))
    return [{"id": r.id, "source": r.source, "event": r.event, "detail": r.detail, "created_at": r.created_at} for r in rows]


@router.get("/voice/history")
def voice_history(db: Db, limit: int = Query(30, ge=1, le=100)) -> list[dict]:
    rows = db.scalars(select(VoiceTranscript).order_by(VoiceTranscript.created_at.desc()).limit(limit))
    return [{"id": row.id, "owner_id": row.owner_id, "transcript": row.transcript,
             "duration_seconds": row.duration_seconds, "engine": row.engine,
             "tools_used": row.tools_used.split(",") if row.tools_used else [], "created_at": row.created_at} for row in rows]


@router.get("/reminders")
def reminders(db: Db, status: str = "pending") -> list[dict]:
    rows = db.scalars(select(Reminder).where(Reminder.status == status).order_by(Reminder.remind_at))
    return [{"id": row.id, "owner_id": row.owner_id, "title": row.title, "remind_at": row.remind_at,
             "display_time": display_local(row.remind_at), "recurrence": row.recurrence, "status": row.status} for row in rows]


@router.post("/reminders", status_code=201)
def create_reminder(payload: ReminderCreate, db: Db) -> dict:
    try: remind_at = parse_reminder_time(payload.remind_at)
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc
    allowed = get_settings().telegram_allowed_user_ids
    owner_id = str(allowed[0]) if allowed else "web"
    row = Reminder(owner_id=owner_id, title=payload.title, remind_at=remind_at, recurrence=payload.recurrence)
    db.add(row); db.commit(); db.refresh(row); record_activity(db, "web", "reminder_created", f"Reminder {row.id} created")
    return {"id": row.id, "title": row.title, "display_time": display_local(row.remind_at), "recurrence": row.recurrence, "status": row.status}


@router.delete("/reminders/{reminder_id}", status_code=204)
def delete_reminder(reminder_id: int, db: Db) -> None:
    row = db.get(Reminder, reminder_id)
    if not row: raise HTTPException(404, "Reminder not found")
    row.status = "cancelled"; db.commit()
