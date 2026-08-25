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
from app.models import Activity, Memory, Task, UploadedFile
from app.schemas.api import ChatRequest, ChatResponse, FileQuestion, MemoryCreate, MemoryOut, TaskCreate, TaskOut, TaskUpdate
from app.services import system
from app.services.activity import record_activity
from app.services.files import read_controlled_file, save_upload
from app.services.hailo import hailo_status
from app.services.ollama import OllamaService

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
    result = await PiPilotAgent().run(payload.message, [row.model_dump() for row in payload.history], db, "web")
    return ChatResponse(response=result.response, tools_used=result.tools_used)


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
    row = UploadedFile(original_name=original, stored_name=stored, content_type=file.content_type, size=size)
    db.add(row); db.commit(); db.refresh(row); record_activity(db, "web", "file_uploaded", f"File {row.id} uploaded")
    return {"id": row.id, "name": row.original_name, "size": row.size}


@router.post("/files/{file_id}/ask", response_model=ChatResponse)
async def ask_file(file_id: int, payload: FileQuestion, db: Db) -> ChatResponse:
    row = db.get(UploadedFile, file_id)
    if not row: raise HTTPException(404, "File not found")
    try: content = read_controlled_file(row.stored_name)
    except OSError as exc: raise HTTPException(404, "Stored file unavailable") from exc
    prompt = f"File: {row.original_name}\nQuestion: {payload.question}\n\nContent:\n{content}"
    try:
        answer = await OllamaService().chat([{"role": "system", "content": "Answer using only the supplied local file. Say when the answer is not present."}, {"role": "user", "content": prompt}])
    except httpx.HTTPError as exc: raise HTTPException(503, "Ollama unavailable") from exc
    record_activity(db, "web", "file_question", f"File {row.id} queried")
    return ChatResponse(response=answer)


@router.get("/activity")
def activity(db: Db, limit: int = Query(50, ge=1, le=200)) -> list[dict]:
    rows = db.scalars(select(Activity).order_by(Activity.created_at.desc()).limit(limit))
    return [{"id": r.id, "source": r.source, "event": r.event, "detail": r.detail, "created_at": r.created_at} for r in rows]

