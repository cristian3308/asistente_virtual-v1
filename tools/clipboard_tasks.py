"""Portapapeles Windows y recordatorios no bloqueantes."""
from __future__ import annotations

import threading
from datetime import datetime, timedelta


def leer_portapapeles() -> str:
    try:
        import pyperclip
        return pyperclip.paste() or "El portapapeles está vacío."
    except Exception as exc:
        return f"No se pudo leer el portapapeles: {exc}"


def copiar_al_portapapeles(texto: str) -> str:
    try:
        import pyperclip
        pyperclip.copy(texto)
        return "Texto copiado al portapapeles."
    except Exception as exc:
        return f"No se pudo copiar al portapapeles: {exc}"


def programar_recordatorio(minutos: int, mensaje: str) -> str:
    minutos = max(1, min(int(minutos), 10080))

    def notify() -> None:
        text = f"⏰ Recordatorio: {mensaje}"
        print(text)
        try:
            from voice.mouth_tts import hablar
            hablar(text)
        except Exception:
            pass

    timer = threading.Timer(minutos * 60, notify)
    timer.daemon = True
    timer.start()
    due = datetime.now() + timedelta(minutes=minutos)
    return f"Recordatorio programado para {due:%Y-%m-%d %H:%M}."
