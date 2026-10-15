"""Puente Telegram restringido a un único usuario autorizado."""
from __future__ import annotations

import logging
from pathlib import Path

from config import settings
from core.self_coder import confirmation_context, reset_confirmation_context

logger = logging.getLogger(__name__)


def _authorized(update) -> bool:
    user = update.effective_user
    allowed = settings.TELEGRAM_ALLOWED_USER_ID
    if not user or not allowed:
        return False
    try:
        authorized = user.id == int(allowed)
    except ValueError:
        authorized = False
    if not authorized:
        logger.warning("Intento Telegram bloqueado: user_id=%s", getattr(user, "id", None))
    return authorized


def run_telegram(brain) -> None:
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_ALLOWED_USER_ID:
        logger.warning("Telegram no iniciado: faltan TELEGRAM_BOT_TOKEN o TELEGRAM_ALLOWED_USER_ID.")
        return
    try:
        from telegram import Update
        from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
    except ImportError:
        logger.warning("python-telegram-bot no está instalado.")
        return

    async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _authorized(update):
            return
        token = confirmation_context(False)
        try:
            answer, motor = brain.ask(update.message.text or "")
        finally:
            reset_confirmation_context(token)
        await update.message.reply_text(f"[{motor}]\n{answer[:4000]}")

    async def voice_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _authorized(update):
            return
        try:
            from voice.ear_stt import transcribir_archivo
            voice = await update.message.voice.get_file()
            path = settings.DATA_DIR / "telegram_voice" / f"{update.message.voice.file_unique_id}.ogg"
            path.parent.mkdir(parents=True, exist_ok=True)
            await voice.download_to_drive(custom_path=str(path))
            text = transcribir_archivo(path)
            token = confirmation_context(False)
            try:
                answer, motor = brain.ask(text)
            finally:
                reset_confirmation_context(token)
            await update.message.reply_text(f"[{motor}]\n{answer[:4000]}")
        except Exception as exc:
            await update.message.reply_text(f"No se pudo procesar el audio: {exc}")

    async def status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if _authorized(update):
            await update.message.reply_text("Asistente conectado y autorizado.")

    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("estado", status_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(MessageHandler(filters.VOICE, voice_handler))
    app.run_polling(drop_pending_updates=True)
