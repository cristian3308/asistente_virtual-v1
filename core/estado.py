"""Estado observable del asistente (pensando, hablando...) para interfaces como el avatar.

Publicar es barato y seguro aunque nadie esté mirando, así que el cerebro y la
voz lo llaman sin saber si el avatar está abierto.
"""
from __future__ import annotations

import threading
import time

ESTADOS = {"idle", "listening", "thinking", "searching", "working", "speaking", "happy", "error", "sleeping"}
DORMIR_TRAS = 180.0      # segundos en reposo antes de dormirse
MANTENER_HABLA = 0.8     # deja la boca moviéndose un poco tras el último fragmento

_lock = threading.Lock()
_estado = {"estado": "idle", "motor": "local", "detalle": "", "cambio": time.monotonic()}
_temporal: tuple[str, float, str] | None = None   # (estado, hasta, detalle) para happy/error breves
_habla_hasta = 0.0
_voz_activa = 0
# Volumen del audio que suena ahora, para mover la boca sílaba por sílaba. El
# avatar lo reproduce con su propio reloj a partir de `inicio`, sin depender del sondeo.
_boca: dict = {"id": 0, "inicio": 0, "paso": 0, "env": []}


def boca(envolvente: list[float], paso_ms: int, inicio_ms: int) -> None:
    """Publica la envolvente (0–1) del audio que empieza a sonar en `inicio_ms` (reloj de pared, ms)."""
    with _lock:
        _boca.update(id=_boca["id"] + 1, inicio=inicio_ms, paso=paso_ms,
                     env=[round(float(v), 2) for v in envolvente])


def publicar(estado: str, motor: str | None = None, detalle: str = "", duracion: float | None = None) -> None:
    """Cambia el estado. Con `duracion` es un estado breve (p. ej. happy) que luego vuelve al anterior."""
    global _temporal, _habla_hasta
    if estado not in ESTADOS:
        return
    now = time.monotonic()
    with _lock:
        if motor:
            _estado["motor"] = motor
        if duracion:
            _temporal = (estado, now + duracion, detalle)
            return
        if estado == "speaking":
            _habla_hasta = now + MANTENER_HABLA
        _estado.update(estado=estado, detalle=detalle, cambio=now)


_subtitulo = {"texto": "", "id": 0}


def subtitulo(texto: str) -> None:
    """La frase que suena ahora, para mostrarla bajo el avatar ("" la borra)."""
    with _lock:
        _subtitulo["texto"] = (texto or "").strip()[:220]
        _subtitulo["id"] += 1


def voz(activa: bool) -> None:
    """La reproducción de audio marca 'speaking' aunque el cerebro ya haya terminado el turno."""
    global _voz_activa
    with _lock:
        _voz_activa = max(0, _voz_activa + (1 if activa else -1))
        _estado["cambio"] = time.monotonic()


def actual() -> dict:
    now = time.monotonic()
    with _lock:
        estado, detalle = _estado["estado"], _estado["detalle"]
        if _temporal and now < _temporal[1]:
            estado, detalle = _temporal[0], _temporal[2]
        elif _voz_activa:
            estado, detalle = "speaking", ""
        elif estado == "idle" and now < _habla_hasta:
            estado = "speaking"
        elif estado == "idle" and now - _estado["cambio"] > DORMIR_TRAS:
            estado = "sleeping"
        resultado = {"estado": estado, "motor": _estado["motor"], "detalle": detalle, "boca_id": _boca["id"],
                     "subtitulo": _subtitulo["texto"] if _voz_activa or estado == "speaking" else ""}
        if _voz_activa:
            resultado["boca"] = dict(_boca)
        return resultado
