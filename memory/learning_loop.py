"""Registro de fallos de herramientas y lecciones persistentes."""
from __future__ import annotations

import traceback


def registrar_fallo(nombre: str, exc: BaseException) -> str:
    lesson = f"La herramienta {nombre} falló con {type(exc).__name__}: {exc}"
    try:
        from tools.memory_tools import guardar_recuerdo_importante
        guardar_recuerdo_importante(lesson, "autoevolucion")
    except Exception:
        pass
    return lesson + "\n" + traceback.format_exc(limit=4)
