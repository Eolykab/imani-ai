import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from app.agent import PiPilotAgent
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.activity import record_activity
from app.tools.registry import restart_approved_service

logger = logging.getLogger(__name__)


class TelegramService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.application: Application | None = None
        self.pending_restarts: dict[int, str] = {}

    def _authorized(self, update: Update) -> bool:
        user = update.effective_user
        return bool(user and user.id in self.settings.telegram_allowed_user_ids)

    async def _guard(self, update: Update) -> bool:
        if self._authorized(update): return True
        user_id = update.effective_user.id if update.effective_user else "unknown"
        logger.warning("Rejected unauthorized Telegram user id=%s", user_id)
        with SessionLocal() as db: record_activity(db, "telegram", "unauthorized_request", f"Rejected user {user_id}")
        if update.effective_message: await update.effective_message.reply_text("Unauthorized.")
        return False

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if await self._guard(update): await update.effective_message.reply_text("PiPilot is ready. Ask me general questions, or ask about this device, notes, tasks, Ollama, and Hailo.")

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if await self._guard(update): await update.effective_message.reply_text("Ask general-knowledge questions in natural language. Commands: /status /health /notes /tasks.")

    async def message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard(update) or not update.effective_message or not update.effective_message.text: return
        text = update.effective_message.text
        user_id = update.effective_user.id
        if user_id in self.pending_restarts:
            service = self.pending_restarts.pop(user_id)
            if text.strip().lower() not in {"confirm", "yes, confirm", "confirm restart"}:
                await update.effective_message.reply_text("Restart cancelled.")
                return
            with SessionLocal() as db:
                record_activity(db, "telegram", "service_restart_executed", f"Approved restart executed for {service}")
            result = await restart_approved_service(service)
            await update.effective_message.reply_text(result["message"] or f"{service}: {result['status']}")
            return
        words = text.strip().lower().split()
        if len(words) == 2 and words[0] == "restart":
            service = words[1]
            if service not in self.settings.pipilot_allowed_services:
                await update.effective_message.reply_text("That service is not approved for management.")
                return
            self.pending_restarts[user_id] = service
            with SessionLocal() as db:
                record_activity(db, "telegram", "service_restart_requested", f"Confirmation requested for {service}")
            await update.effective_message.reply_text(f"Restarting {service} may temporarily disconnect services. Reply Confirm to continue; any other reply cancels.")
            return
        aliases = {"/status": "Give me a concise system status", "/health": "Give me a system health report", "/notes": "Show my notes", "/tasks": "Show my tasks"}
        text = aliases.get(text.split()[0], text)
        with SessionLocal() as db:
            record_activity(db, "telegram", "message_received", "Authorized message received")
            result = await PiPilotAgent().run(text, [], db, "telegram")
        await update.effective_message.reply_text(result.response[:4096])

    async def launch(self) -> None:
        if not self.settings.telegram_bot_token: return
        self.application = Application.builder().token(self.settings.telegram_bot_token).build()
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.message))
        for command in ("status", "health", "notes", "tasks"):
            self.application.add_handler(CommandHandler(command, self.message))
        await self.application.initialize(); await self.application.start(); await self.application.updater.start_polling(drop_pending_updates=True)
        logger.info("Telegram polling started")

    async def shutdown(self) -> None:
        if self.application:
            await self.application.updater.stop(); await self.application.stop(); await self.application.shutdown()
