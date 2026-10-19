"""Registro de fallos de herramientas para aprender sin ensuciar la memoria personal."""
from __future__ import annotations

import json
import traceback
from datetime import datetime

from config.settings import DATA_DIR

FAILURE_LOG = DATA_DIR / "aprendizaje" / "fallos_herramientas.jsonl"


def registrar_fallo(nombre: str, exc: BaseException) -> str:
    lesson = f"La herramienta {nombre} falló con {type(exc).__name__}: {exc}"
    try:
        FAILURE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with FAILURE_LOG.open("a", encoding="utf-8") as log:
            log.write(json.dumps({"fecha": datetime.now().isoformat(timespec="seconds"), "herramienta": nombre,
                                  "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return lesson + "\n" + traceback.format_exc(limit=4)


def registrar_fallo_habilidad(nombre: str, argumentos: dict, error: str) -> None:
    """Fallo de una habilidad aprendida con los argumentos exactos, para poder repararla."""
    try:
        FAILURE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with FAILURE_LOG.open("a", encoding="utf-8") as log:
            log.write(json.dumps({"fecha": datetime.now().isoformat(timespec="seconds"), "herramienta": nombre,
                                  "argumentos": argumentos, "error": error[:500], "habilidad": True},
                                 ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass


def ultimo_fallo(nombre: str) -> dict | None:
    return next((f for f in reversed(fallos_recientes(200)) if f.get("herramienta") == nombre), None)


def fallos_recientes(limite: int = 20) -> list[dict]:
    """Últimos fallos registrados, para revisar qué habilidades conviene mejorar."""
    try:
        lines = FAILURE_LOG.read_text(encoding="utf-8").splitlines()[-limite:]
    except OSError:
        return []
    return [json.loads(line) for line in lines if line.strip()]
