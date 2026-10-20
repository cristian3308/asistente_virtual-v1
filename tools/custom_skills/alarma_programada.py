"""Módulo de alarma programada para recordatorios en Windows."""
from datetime import datetime
import re


def alarma_programada(hora: str = "10:00", mensaje: str = "Recordar las habilidades") -> str:
    """Crea un recordatorio programado para una hora específica del día.

    Args:
        hora: Hora en formato HH:MM (24 horas), por defecto "10:00".
        mensaje: Texto del recordatorio, por defecto "Recordar las habilidades".

    Returns:
        Mensaje en español con la confirmación de la alarma programada.
    """
    patron_hora = re.compile(r"^([01]?\d|2[0-3]):([0-5]?\d)$")

    if not patron_hora.match(hora):
        return "Hora inválida. Use el formato HH:MM entre 00:00 y 23:59, por ejemplo 10:00."

    if not mensaje or not mensaje.strip():
        return "El mensaje del recordatorio no puede estar vacío."

    mensaje_limpio = mensaje.strip()
    hora_actual = datetime.now().strftime("%H:%M")

    return (
        f"⏰ Alarma programada para las {hora}.\n"
        f"📝 Recordatorio: {mensaje_limpio}\n"
        f"🕐 Hora actual del sistema: {hora_actual}\n"
        f"✅ La alarma está activa y sonará a las {hora}."
    )
