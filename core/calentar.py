"""Deja el modelo local cargado en la GPU al arrancar, antes de que le hables.

Medido 2026-10-27: la primera pregunta "en frío" tardaba 35 s solo en cargar el modelo
(63 s si a la vez arrancaban Hindsight, Whisper y la memoria). Ya cargado responde en 0,1 s.
Aquí se carga en segundo plano nada más abrir el asistente y, al terminar, se arranca lo
pesado que puede esperar (Hindsight), para que no compitan por el disco y el procesador.
"""
from __future__ import annotations

import threading
import time

from config import settings

estado = {"listo": False, "segundos": None, "error": None}
_listo = threading.Event()


def cargar_modelo_local(mantener: str = "24h") -> float:
    """Pide a Ollama que cargue el modelo sin generar nada. Devuelve los segundos que tardó."""
    import httpx
    inicio = time.perf_counter()
    respuesta = httpx.post("http://127.0.0.1:11434/api/generate", timeout=300,
                           json={"model": settings.MODEL_LOCAL, "keep_alive": mantener})
    respuesta.raise_for_status()
    return time.perf_counter() - inicio


def en_segundo_plano(despues=None) -> None:
    """Carga el modelo en un hilo y luego llama a `despues()` (p. ej. arrancar Hindsight)."""
    def trabajar() -> None:
        try:
            if settings.ollama_activo():
                estado["segundos"] = round(cargar_modelo_local(), 1)
            estado["listo"] = True
        except Exception as exc:
            estado["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            _listo.set()
            if despues is not None:
                try:
                    despues()
                except Exception:
                    pass
    threading.Thread(target=trabajar, name="calentar-modelo", daemon=True).start()


def esperar(segundos: float) -> bool:
    return _listo.wait(segundos)
