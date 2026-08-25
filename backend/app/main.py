from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import Base, engine
from app.services.telegram import TelegramService

configure_logging()
telegram = TelegramService()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    Path("data").mkdir(exist_ok=True); settings.pipilot_upload_dir.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    await telegram.launch()
    yield
    await telegram.shutdown()


app = FastAPI(title="PiPilot API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])
app.include_router(router)

frontend = get_settings().frontend_dir
if frontend.exists():
    app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")

