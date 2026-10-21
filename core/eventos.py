"""Lo que pasa en el asistente, en vivo, para verlo desde el celular.

Guarda en memoria los últimos eventos (mensajes, respuestas, herramientas, avisos)
con un número creciente; la app pide "lo nuevo desde el número N" y espera un rato
si aún no hay nada (long polling). No se guarda en disco: para el historial está la
auditoría.
"""
from __future__ import annotations

import threading
from collections import deque
from datetime import datetime

MAXIMO = 400
TEXTO_MAXIMO = 1500

_cond = threading.Condition()
_eventos: deque[dict] = deque(maxlen=MAXIMO)
_ultimo = 0


def publicar(tipo: str, texto: str, origen: str | None = None, **extra) -> None:
    """tipo: mensaje, respuesta, herramienta, aviso, estado. Nunca lanza."""
    global _ultimo
    try:
        if origen is None:
            from core import auditoria
            origen = auditoria._origen.get()
        texto = str(texto or "")
        with _cond:
            _ultimo += 1
            _eventos.append({"id": _ultimo, "hora": datetime.now().isoformat(timespec="seconds"), "tipo": tipo,
                             "origen": origen, "texto": texto[:TEXTO_MAXIMO] + ("…" if len(texto) > TEXTO_MAXIMO else ""),
                             **extra})
            _cond.notify_all()
    except Exception:
        pass


def desde(id_evento: int, espera: float = 0.0) -> list[dict]:
    """Eventos con id mayor que `id_evento`; si no hay, espera hasta `espera` segundos a que llegue uno."""
    with _cond:
        if espera > 0 and _ultimo <= id_evento:
            _cond.wait_for(lambda: _ultimo > id_evento, timeout=espera)
        return [e for e in _eventos if e["id"] > id_evento]


def ultimo() -> int:
    return _ultimo
