from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=30)


class ChatResponse(BaseModel):
    response: str
    tools_used: list[str] = []


class MemoryCreate(BaseModel):
    content: str = Field(min_length=1, max_length=5000)


class MemoryOut(MemoryCreate):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=5000)
    due_date: datetime | None = None


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=5000)
    status: str | None = None
    due_date: datetime | None = None


class TaskOut(TaskCreate):
    id: int
    status: str
    created_at: datetime
    completed_at: datetime | None
    model_config = ConfigDict(from_attributes=True)


class FileQuestion(BaseModel):
    question: str = Field(min_length=1, max_length=2000)

