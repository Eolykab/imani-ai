import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.session import Base
from app.tools.registry import execute_tool


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.mark.asyncio
async def test_system_health_contains_real_metrics(db):
    result = await execute_tool("system_health", {}, db)
    assert 0 <= result["cpu"]["percent"] <= 100
    assert result["memory"]["total"] > 0


@pytest.mark.asyncio
async def test_unknown_tool_is_rejected(db):
    with pytest.raises(ValueError, match="Unknown"):
        await execute_tool("shell", {"command": "whoami"}, db)


@pytest.mark.asyncio
async def test_memory_shared_in_database(db):
    created = await execute_tool("create_memory", {"text": "presentation tomorrow"}, db)
    listed = await execute_tool("list_memories", {"query": "presentation"}, db)
    assert listed[0]["id"] == created["id"]


@pytest.mark.asyncio
async def test_service_allowlist_rejects_arbitrary_service(db):
    result = await execute_tool("service_status", {"service": "unapproved"}, db)
    assert result["allowed"] is False
