"""Portapapeles de Windows y recordatorios persistentes."""
from __future__ import annotations

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


def programar_recordatorio(mensaje: str, minutos: int = 0, hora: str = "") -> str:
    """Recordatorio persistente: sobrevive a cerrar el programa y avisa también por Telegram.

    `hora` admite "HH:MM" (hoy, o mañana si ya pasó); si no, se usan `minutos` desde ahora.
    """
    from core import tareas

    ahora = datetime.now().replace(second=0, microsecond=0)
    if hora:
        try:
            hh, mm = (int(parte) for parte in hora.strip().split(":")[:2])
            cuando = ahora.replace(hour=hh, minute=mm)
        except ValueError:
            return f"Hora no válida: '{hora}'. Usa HH:MM, por ejemplo 18:30."
        if cuando <= datetime.now():
            cuando += timedelta(days=1)
    else:
        cuando = datetime.now().replace(microsecond=0) + timedelta(minutes=max(1, min(int(minutos or 1), 10080)))
    id_tarea = tareas.crear("recordatorio", mensaje, cuando=cuando)
    return f"Recordatorio [{id_tarea}] programado para {cuando:%Y-%m-%d %H:%M}: {mensaje}"
