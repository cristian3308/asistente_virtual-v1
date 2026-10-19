"""Puente Telegram restringido a un único usuario autorizado."""
from __future__ import annotations

import asyncio
import logging
import shutil
import time
from pathlib import Path

from config import settings
from core.self_coder import confirmation_context, reset_confirmation_context

logger = logging.getLogger(__name__)
ESPERA_REINTENTO = 60   # segundos entre intentos de conexión si no hay red


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
    from telegram.error import InvalidToken, NetworkError
    _sin_trazas_de_red()
    while True:
        # Bucle de eventos nuevo en cada intento: el anterior queda cerrado si falló.
        asyncio.set_event_loop(asyncio.new_event_loop())
        try:
            _ejecutar_bot(brain, Update, Application, CommandHandler, ContextTypes, MessageHandler, filters)
            return
        except InvalidToken:
            _avisar("[red]Telegram se detuvo: el token no es válido. Revisa TELEGRAM_BOT_TOKEN en .env.[/red]")
            return
        except NetworkError as exc:  # sin internet o Telegram lento al arrancar: reintenta solo
            _avisar(f"[yellow]Telegram no pudo conectarse ({type(exc).__name__}). "
                    f"Reintento en {ESPERA_REINTENTO} s; el resto del asistente sigue funcionando.[/yellow]")
            time.sleep(ESPERA_REINTENTO)
        except Exception as exc:  # otro proceso usando el mismo bot, etc.
            _avisar(f"[red]Telegram se detuvo: {type(exc).__name__}: "
                    f"{str(exc).replace(settings.TELEGRAM_BOT_TOKEN, '<token>')}[/red]")
            return


def _sin_trazas_de_red() -> None:
    """Los cortes de red de Telegram se avisan en una línea; sin el traceback enorme en la consola."""
    class _SinTraza(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            if record.module == "networkloop":
                record.exc_info = None
                record.exc_text = None
            return True

    logging.getLogger("telegram.ext").addFilter(_SinTraza())


def _ejecutar_bot(brain, Update, Application, CommandHandler, ContextTypes, MessageHandler, filters) -> None:
    from core import auditoria
    # Las tareas del bot heredan este contexto: todo lo que hagan queda auditado como 'telegram'.
    auditoria.origen("telegram")

    async def parar_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if _authorized(update):
            await update.message.reply_text(auditoria.detener("telegram"))

    async def tareas_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _authorized(update):
            return
        from core import tareas
        activas = tareas.listar()
        texto = chr(10).join(tareas.describir(t) for t in activas) or "No hay tareas pendientes."
        await update.message.reply_text(texto + chr(10) + chr(10) + "Nueva: /tarea <objetivo> · cancelar: /cancelar <id>")

    async def tarea_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _authorized(update):
            return
        from core import tareas
        objetivo = " ".join(context.args or [])
        if not objetivo:
            await update.message.reply_text("Uso: /tarea <lo que quieres que haga en segundo plano>")
            return
        id_tarea = tareas.crear("agente", objetivo, origen="telegram")
        await update.message.reply_text(f"Tarea [{id_tarea}] en cola. Te aviso aquí cuando termine.")

    async def cancelar_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _authorized(update):
            return
        from core import tareas
        id_tarea = "".join(context.args or []).strip("[] ")
        await update.message.reply_text(f"Tarea {id_tarea} cancelada." if tareas.cancelar(id_tarea) else "No encontré esa tarea activa.")

    async def reanudar_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if _authorized(update):
            await update.message.reply_text(auditoria.reanudar())

    async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _authorized(update):
            return
        token = confirmation_context(False)
        try:
            answer, motor = await asyncio.to_thread(brain.ask, update.message.text or "")
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
                text = await asyncio.to_thread(transcribir_archivo, path)
            finally:
                path.unlink(missing_ok=True)  # el audio no se guarda una vez transcrito
            if not text:
                await update.message.reply_text("No entendí el audio. ¿Me lo repites?")
                return
            token = confirmation_context(False)
            try:
                answer, motor = await asyncio.to_thread(brain.ask, text)
            finally:
                reset_confirmation_context(token)
            await update.message.reply_text(f"🎙️ Entendí: {text}\n\n[{motor}]\n{answer[:3900]}")
            # Si me hablaste con voz, te respondo también con voz (la elegida con /voz_usar).
            from voice.mouth_tts import nota_de_voz
            ogg = await asyncio.to_thread(nota_de_voz, answer)
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
                "/tarea <objetivo> trabajo en segundo plano · /tareas · /captura foto de la pantalla · /parar emergencia · /reanudar · /estado"
            )

    async def al_conectar(application) -> None:
        bot = await application.bot.get_me()
        _avisar(f"[green]✅ Telegram conectado: @{bot.username}. Escríbele /start desde tu Telegram. "
                "(Lo que enviaste con el asistente cerrado se descarta: vuelve a enviarlo.)[/green]")

    # concurrent_updates: /parar se atiende aunque haya una respuesta larga en curso.
    # Tiempos amplios: al arrancar el PC está ocupado cargando modelos y la red puede ir lenta.
    app = (Application.builder().token(settings.TELEGRAM_BOT_TOKEN).post_init(al_conectar)
           .concurrent_updates(True).connect_timeout(20).read_timeout(30).write_timeout(30)
           .get_updates_read_timeout(40).build())
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("estado", status_handler))
    app.add_handler(CommandHandler("captura", captura_handler))
    app.add_handler(CommandHandler("parar", parar_handler))
    app.add_handler(CommandHandler("reanudar", reanudar_handler))
    app.add_handler(CommandHandler("tareas", tareas_handler))
    app.add_handler(CommandHandler("tarea", tarea_handler))
    app.add_handler(CommandHandler("cancelar", cancelar_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(MessageHandler(filters.VOICE, voice_handler))
    app.run_polling(drop_pending_updates=True, bootstrap_retries=5)
