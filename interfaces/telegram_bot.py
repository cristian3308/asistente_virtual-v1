"""Puente Telegram restringido a un único usuario autorizado."""
from __future__ import annotations

import logging
import shutil
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
        # Visible en la consola: si eres tú, este es el número que va en TELEGRAM_ALLOWED_USER_ID.
        _avisar(f"[yellow]Telegram: mensaje ignorado de id {getattr(user, 'id', '?')} "
                f"(@{getattr(user, 'username', None) or 'sin usuario'}); no coincide con TELEGRAM_ALLOWED_USER_ID.[/yellow]")
    return authorized


def _avisar(texto: str) -> None:
    from rich.console import Console
    Console().print(texto)


def run_telegram(brain) -> None:
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_ALLOWED_USER_ID:
        _avisar("[yellow]Telegram no iniciado: faltan TELEGRAM_BOT_TOKEN o TELEGRAM_ALLOWED_USER_ID en .env.[/yellow]")
        return
    try:
        from telegram import Update
        from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
    except ImportError:
        _avisar("[red]Telegram no iniciado: python-telegram-bot no está instalado.[/red]")
        return
    try:
        _ejecutar_bot(brain, Update, Application, CommandHandler, ContextTypes, MessageHandler, filters)
    except Exception as exc:  # token revocado, sin internet, otro proceso usando el mismo bot...
        _avisar(f"[red]Telegram se detuvo: {type(exc).__name__}: "
                f"{str(exc).replace(settings.TELEGRAM_BOT_TOKEN, '<token>')}[/red]")


def _ejecutar_bot(brain, Update, Application, CommandHandler, ContextTypes, MessageHandler, filters) -> None:
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
            try:
                text = transcribir_archivo(path)
            finally:
                path.unlink(missing_ok=True)  # el audio no se guarda una vez transcrito
            if not text:
                await update.message.reply_text("No entendí el audio. ¿Me lo repites?")
                return
            token = confirmation_context(False)
            try:
                answer, motor = brain.ask(text)
            finally:
                reset_confirmation_context(token)
            await update.message.reply_text(f"🎙️ Entendí: {text}\n\n[{motor}]\n{answer[:3900]}")
            # Si me hablaste con voz, te respondo también con voz (la elegida con /voz_usar).
            from voice.mouth_tts import nota_de_voz
            ogg = nota_de_voz(answer)
            if ogg is not None:
                try:
                    with ogg.open("rb") as audio:
                        await update.message.reply_voice(audio)
                finally:
                    shutil.rmtree(ogg.parent, ignore_errors=True)
        except Exception as exc:
            await update.message.reply_text(f"No se pudo procesar el audio: {exc}")

    async def status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if _authorized(update):
            await update.message.reply_text("Asistente conectado y autorizado.")

    async def captura_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Envía una foto de la pantalla del PC. Solo al usuario autorizado; no se guarda en el PC."""
        if not _authorized(update):
            return
        import tempfile
        import mss
        from PIL import Image
        carpeta = Path(tempfile.mkdtemp(prefix="asistente_captura_"))
        try:
            archivo = carpeta / "pantalla.jpg"
            with mss.MSS() as pantalla:
                imagen = pantalla.grab(pantalla.monitors[1])
                Image.frombytes("RGB", imagen.size, imagen.rgb).save(archivo, quality=80)
            with archivo.open("rb") as foto:
                await update.message.reply_photo(foto, caption="Pantalla del PC ahora mismo.")
        except Exception as exc:
            await update.message.reply_text(f"No pude capturar la pantalla: {exc}")
        finally:
            shutil.rmtree(carpeta, ignore_errors=True)

    async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if _authorized(update):
            await update.message.reply_text(
                "Hola, Cristhian. Escríbeme o mándame una nota de voz y te respondo (con voz si me hablas).\n"
                "Por seguridad, desde aquí no ejecuto PowerShell ni instalo habilidades nuevas.\n"
                "/captura te envía una foto de la pantalla del PC · /estado comprueba la conexión."
            )

    async def al_conectar(application) -> None:
        bot = await application.bot.get_me()
        _avisar(f"[green]✅ Telegram conectado: @{bot.username}. Escríbele /start desde tu Telegram. "
                "(Lo que enviaste con el asistente cerrado se descarta: vuelve a enviarlo.)[/green]")

    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).post_init(al_conectar).build()
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("estado", status_handler))
    app.add_handler(CommandHandler("captura", captura_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(MessageHandler(filters.VOICE, voice_handler))
    app.run_polling(drop_pending_updates=True)
