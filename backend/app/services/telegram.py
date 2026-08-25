import logging
import tempfile
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters
from sqlalchemy import select

from app.agent import PiPilotAgent
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.activity import record_activity
from app.tools.registry import restart_approved_service
from app.services.voice import VoiceUnavailable, transcribe_hailo_voice
from app.models import Activity, Reminder, Task, VoiceTranscript
from app.services import system
from app.services.ollama import OllamaService
from app.services.reminders import display_local

logger = logging.getLogger(__name__)


class TelegramService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.application: Application | None = None
        self.pending_restarts: dict[int, str] = {}
        self.scheduler_task: asyncio.Task | None = None

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

    async def tasks_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard(update) or not update.effective_user or not update.effective_message: return
        owner = str(update.effective_user.id)
        with SessionLocal() as db:
            rows = list(db.scalars(select(Task).where(Task.owner_id.in_([owner, "shared"])).order_by(Task.created_at.desc()).limit(20)))
        if not rows:
            await update.effective_message.reply_text("You have no tasks.")
            return
        lines, buttons = [], []
        for row in rows:
            icon = "✅" if row.status == "completed" else "▫️"
            lines.append(f"{icon} #{row.id} {row.title}")
            buttons.append([InlineKeyboardButton(f"{'Reopen' if row.status == 'completed' else 'Complete'} #{row.id}", callback_data=f"task:toggle:{row.id}"),
                            InlineKeyboardButton(f"Delete #{row.id}", callback_data=f"task:delete:{row.id}")])
        await update.effective_message.reply_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(buttons))

    async def task_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not query or not update.effective_user or update.effective_user.id not in self.settings.telegram_allowed_user_ids: return
        await query.answer()
        try: _, action, raw_id = query.data.split(":", 2); task_id = int(raw_id)
        except (ValueError, AttributeError): return
        owner = str(update.effective_user.id)
        with SessionLocal() as db:
            row = db.get(Task, task_id)
            if not row or row.owner_id not in {owner, "shared"}:
                await query.edit_message_text("Task no longer exists."); return
            if action == "delete": db.delete(row); message = f"Deleted task #{task_id}."
            else:
                row.status = "pending" if row.status == "completed" else "completed"
                row.completed_at = None if row.status == "pending" else datetime.now(timezone.utc)
                message = f"Task #{task_id} is now {row.status}."
            db.commit(); record_activity(db, "telegram", f"task_{action}", message)
        await query.edit_message_text(message)

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
            result = await PiPilotAgent().run(text, [], db, "telegram", str(user_id))
        await update.effective_message.reply_text(result.response[:4096])

    async def voice_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard(update) or not update.effective_message or not update.effective_message.voice:
            return
        voice = update.effective_message.voice
        if voice.duration > self.settings.pipilot_voice_max_seconds:
            await update.effective_message.reply_text(f"Voice note is too long. Maximum: {self.settings.pipilot_voice_max_seconds} seconds.")
            return
        max_bytes = self.settings.pipilot_max_upload_mb * 1024 * 1024
        if voice.file_size and voice.file_size > max_bytes:
            await update.effective_message.reply_text("Voice note exceeds the configured upload limit.")
            return
        self.settings.pipilot_upload_dir.mkdir(parents=True, exist_ok=True)
        await update.effective_message.reply_text("🎙️ Hailo-8 is transcribing your voice note…")
        with SessionLocal() as db:
            record_activity(db, "telegram", "voice_received", f"Authorized voice note received ({voice.duration}s)")
        try:
            with tempfile.TemporaryDirectory(prefix="voice-", dir=self.settings.pipilot_upload_dir) as temporary:
                directory = Path(temporary)
                source, wav = directory / "telegram.ogg", directory / "audio.wav"
                telegram_file = await context.bot.get_file(voice.file_id)
                await telegram_file.download_to_drive(custom_path=source)
                transcript = await transcribe_hailo_voice(source, wav)
            with SessionLocal() as db:
                record_activity(db, "hailo", "voice_transcribed", f"Hailo-8 transcription completed ({voice.duration}s)")
                result = await PiPilotAgent().run(transcript["text"], [], db, "telegram_voice", str(update.effective_user.id))
                db.add(VoiceTranscript(owner_id=str(update.effective_user.id), transcript=transcript["text"],
                                       duration_seconds=voice.duration, engine=transcript["engine"],
                                       tools_used=",".join(result.tools_used) or None))
                db.commit()
            reply = f"🎙️ “{transcript['text']}”\n\n{result.response}"
            await update.effective_message.reply_text(reply[:4096])
        except VoiceUnavailable as exc:
            logger.warning("Voice transcription unavailable: %s", exc)
            with SessionLocal() as db:
                record_activity(db, "hailo", "voice_failed", str(exc))
            await update.effective_message.reply_text(f"Voice transcription is unavailable: {exc}")
        except (OSError, RuntimeError) as exc:
            logger.exception("Voice note processing failed")
            await update.effective_message.reply_text(f"Voice note processing failed safely: {type(exc).__name__}")

    async def launch(self) -> None:
        if not self.settings.telegram_bot_token: return
        self.application = Application.builder().token(self.settings.telegram_bot_token).build()
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.message))
        self.application.add_handler(MessageHandler(filters.VOICE, self.voice_message))
        self.application.add_handler(CommandHandler("tasks", self.tasks_command))
        self.application.add_handler(CallbackQueryHandler(self.task_callback, pattern=r"^task:(toggle|delete):\d+$"))
        for command in ("status", "health", "notes"):
            self.application.add_handler(CommandHandler(command, self.message))
        await self.application.initialize(); await self.application.start(); await self.application.updater.start_polling(drop_pending_updates=True)
        self.scheduler_task = asyncio.create_task(self._scheduler_loop())
        logger.info("Telegram polling started")

    async def shutdown(self) -> None:
        if self.scheduler_task:
            self.scheduler_task.cancel()
            try: await self.scheduler_task
            except asyncio.CancelledError: pass
        if self.application:
            await self.application.updater.stop(); await self.application.stop(); await self.application.shutdown()

    async def _scheduler_loop(self) -> None:
        while True:
            try:
                await self._deliver_reminders()
                await self._deliver_briefings()
            except Exception:
                logger.exception("Telegram scheduler iteration failed")
            await asyncio.sleep(30)

    async def _deliver_reminders(self) -> None:
        if not self.application: return
        now = datetime.utcnow()
        with SessionLocal() as db:
            rows = list(db.scalars(select(Reminder).where(Reminder.status == "pending", Reminder.remind_at <= now).limit(50)))
            for row in rows:
                if row.owner_id.isdigit() and int(row.owner_id) in self.settings.telegram_allowed_user_ids:
                    await self.application.bot.send_message(int(row.owner_id), f"⏰ Reminder\n\n{row.title}\n{display_local(row.remind_at)}")
                    row.delivered_at = now
                    if row.recurrence == "daily": row.remind_at += timedelta(days=1)
                    elif row.recurrence == "weekly": row.remind_at += timedelta(days=7)
                    else: row.status = "delivered"
                    record_activity(db, "telegram", "reminder_delivered", f"Reminder {row.id} delivered")
            db.commit()

    async def _deliver_briefings(self) -> None:
        if not self.application: return
        local_now = datetime.now(ZoneInfo(self.settings.pipilot_timezone))
        if local_now.hour != self.settings.pipilot_daily_briefing_hour: return
        today = local_now.date().isoformat()
        ollama = await OllamaService().status()
        health = system.system_health()
        with SessionLocal() as db:
            for user_id in self.settings.telegram_allowed_user_ids:
                marker = f"{user_id}:{today}"
                sent = db.scalar(select(Activity).where(Activity.event == "daily_briefing", Activity.detail == marker).limit(1))
                if sent: continue
                owner = str(user_id)
                pending = len(list(db.scalars(select(Task).where(Task.owner_id.in_([owner, "shared"]), Task.status == "pending"))))
                reminders = len(list(db.scalars(select(Reminder).where(Reminder.owner_id == owner, Reminder.status == "pending"))))
                text = (f"☀️ PiPilot Daily Briefing\n\nTasks pending: {pending}\nReminders: {reminders}\n"
                        f"CPU: {health['cpu']['percent']}%\nRAM: {health['memory']['percent']}%\n"
                        f"Ollama: {'ready' if ollama['model_ready'] else 'unavailable'}\nUptime: {health['uptime']['human']}")
                await self.application.bot.send_message(user_id, text)
                db.add(Activity(source="telegram", event="daily_briefing", detail=marker)); db.commit()
