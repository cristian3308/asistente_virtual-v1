"""Avisos al usuario: consola, voz (si está activa) y Telegram.

Telegram se usa por la API HTTP directamente, así los avisos llegan aunque el bot no
esté atendiendo mensajes en ese momento. Solo se envía al usuario autorizado.
"""
from __future__ import annotations

import threading

from config import settings

voz_activa = lambda: False  # noqa: E731 — main.py la sustituye por el estado real de /voz


def notificar(texto: str, telegram: bool = True) -> None:
    from rich.console import Console
    Console().print(f"[bold cyan]🔔 {texto}[/bold cyan]")
    if voz_activa():
        def hablar_aviso() -> None:
            try:
                from voice.mouth_tts import hablar
                hablar(texto)
            except Exception:
                pass
        threading.Thread(target=hablar_aviso, name="aviso-voz", daemon=True).start()
    if telegram:
        enviar_telegram(texto)
    try:
        from interfaces import push
        push.enviar_en_segundo_plano(texto)   # al celular, aunque la app esté cerrada
    except Exception:
        pass


def enviar_telegram(texto: str) -> bool:
    """Envía un mensaje al usuario autorizado. Devuelve False si no está configurado o falla."""
    if not (settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_ALLOWED_USER_ID.isdigit()):
        return False
    try:
        import httpx
        respuesta = httpx.post(
            f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": int(settings.TELEGRAM_ALLOWED_USER_ID), "text": texto[:4000]},
            timeout=15,
        )
        return respuesta.status_code == 200
    except Exception:
        return False
