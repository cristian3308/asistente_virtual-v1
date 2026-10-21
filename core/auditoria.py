"""Registro auditable de acciones y parada de emergencia.

Cada herramienta ejecutada, confirmación pedida, habilidad instalada o escalado a la
nube queda en `data/auditoria/acciones.jsonl` (una línea JSON por acción, solo se
añade). Los argumentos se recortan y se ocultan los valores que parecen secretos.

La parada de emergencia es un interruptor global: con `detener()` el cerebro corta la
respuesta en curso, no ejecuta más herramientas y las tareas en segundo plano se pausan
hasta `reanudar()`.
"""
from __future__ import annotations

import contextvars
import json
import re
import threading
from datetime import datetime

from config import settings

REGISTRO = settings.DATA_DIR / "auditoria" / "acciones.jsonl"

_origen = contextvars.ContextVar("origen_accion", default="consola")
_lock = threading.Lock()
_parada = threading.Event()
_SECRETO = re.compile(r"(?i)(token|key|clave|password|contraseña|secret)[\"']?\s*[:=]\s*[\"']?[^\s,\"'}]+")
_PATRON_TOKEN = re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b|\bsk-[A-Za-z0-9_-]{20,}\b")


def origen(nombre: str):
    """Marca de dónde viene la orden (consola, telegram, tarea…); devuelve el token para restaurar."""
    return _origen.set(nombre)


def restaurar_origen(token) -> None:
    _origen.reset(token)


def _limpiar(valor, limite: int = 300) -> str:
    texto = valor if isinstance(valor, str) else json.dumps(valor, ensure_ascii=False, default=str)
    texto = _PATRON_TOKEN.sub("<oculto>", _SECRETO.sub(lambda m: f"{m.group(1)}=<oculto>", texto))
    for secreto in (settings.API_KEY, settings.TELEGRAM_BOT_TOKEN):
        if secreto:
            texto = texto.replace(secreto, "<oculto>")
    return texto if len(texto) <= limite else texto[:limite] + "…"


def registrar(tipo: str, nombre: str, detalle=None, resultado=None, ok: bool = True, **extra) -> None:
    """Añade una acción al registro. Nunca lanza: auditar no debe romper el asistente."""
    entrada = {
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "origen": _origen.get(),
        "tipo": tipo,                # herramienta, confirmacion, habilidad, escalado, parada, tarea
        "nombre": nombre,
        "detalle": _limpiar(detalle) if detalle is not None else "",
        "resultado": _limpiar(resultado, 200) if resultado is not None else "",
        "ok": ok,
        **{k: _limpiar(v, 120) if isinstance(v, str) else v for k, v in extra.items()},
    }
    try:
        with _lock:
            REGISTRO.parent.mkdir(parents=True, exist_ok=True)
            with REGISTRO.open("a", encoding="utf-8") as archivo:
                archivo.write(json.dumps(entrada, ensure_ascii=False) + "\n")
    except OSError:
        pass
    # La misma acción (ya sin secretos) se ve en vivo en la app del celular.
    from core import eventos
    eventos.publicar("herramienta" if tipo == "herramienta" else "aviso",
                     f"{nombre}" + (f" → {entrada['resultado']}" if entrada["resultado"] else ""),
                     origen=entrada["origen"], ok=ok, accion=tipo)


def recientes(limite: int = 20) -> list[dict]:
    try:
        lineas = REGISTRO.read_text(encoding="utf-8").splitlines()[-limite:]
    except OSError:
        return []
    salida = []
    for linea in lineas:
        try:
            salida.append(json.loads(linea))
        except ValueError:
            continue
    return salida


# --- Parada de emergencia ---------------------------------------------------

class Detenido(RuntimeError):
    """El usuario activó la parada de emergencia."""


def detener(motivo: str = "") -> str:
    _parada.set()
    registrar("parada", "detener", motivo)
    try:  # Silencia la voz que esté sonando.
        import pygame
        if pygame.mixer.get_init():
            pygame.mixer.stop()
            pygame.mixer.music.stop()
    except Exception:
        pass
    return "⛔ Parada de emergencia activada: no ejecuto más acciones ni tareas hasta /reanudar."


def reanudar() -> str:
    _parada.clear()
    registrar("parada", "reanudar")
    return "▶ Reanudado: vuelvo a atender órdenes y tareas."


def detenido() -> bool:
    return _parada.is_set()


def comprobar() -> None:
    """Lanza `Detenido` si la parada está activa (para cortar bucles largos)."""
    if _parada.is_set():
        raise Detenido("Detenido por el usuario (/reanudar para continuar).")
