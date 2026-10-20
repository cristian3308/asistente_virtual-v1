"""Módulo para preparar la configuración de alarmas programadas."""
import re

def configurar_alarma(hora: str = "12:00", mensaje: str = "Mediodía") -> str:
    """
    Prepara la configuración de una alarma para una hora específica del día.

    Args:
        hora: Hora de la alarma en formato HH:MM (24 horas). Por defecto "12:00".
        mensaje: Descripción o etiqueta de la alarma.

    Returns:
        Cadena en español con los detalles de la alarma preparada.
    """
    patron = r"^([01]?\d|2[0-3]):([0-5]\d)$"
    coincidencia = re.match(patron, hora.strip())

    if not coincidencia:
        return "Hora inválida. Debe usar el formato HH:MM con valores entre 00:00 y 23:59."

    horas = int(coincidencia.group(1))
    minutos = int(coincidencia.group(2))
    hora_formato = "{:02d}:{:02d}".format(horas, minutos)

    if horas == 0:
        doce_horas = "12:{:02d} AM".format(minutos)
    elif horas < 12:
        doce_horas = "{}:{:02d} AM".format(horas, minutos)
    elif horas == 12:
        doce_horas = "12:{:02d} PM (mediodía)".format(minutos)
    else:
        doce_horas = "{}:{:02d} PM".format(horas - 12, minutos)

    texto_mensaje = mensaje.strip()
    if not texto_mensaje:
        texto_mensaje = "Sin mensaje"

    return (
        "Alarma configurada para las {h} ({d}). "
        "Mensaje: {m}. "
        "La alarma sonará automáticamente a esa hora.".format(
            h=hora_formato, d=doce_horas, m=texto_mensaje
        )
    )
