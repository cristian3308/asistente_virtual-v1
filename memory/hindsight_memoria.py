"""Memoria de largo plazo con Hindsight: recuerda conversaciones y saca conclusiones.

El servidor corre aparte (servicios/hindsight_servidor.py, Python 3.12) y aquí se le
habla por HTTP local. Si no está disponible, todo sigue igual que antes: nunca bloquea
ni rompe una respuesta.

- recordar(pregunta): recuerdos relacionados en ~0,3 s, antes de responder.
- guardar_turno(...): guarda la conversación en segundo plano (tarda 3–7 s con Ollama).
"""
from __future__ import annotations

import queue
import subprocess
import threading
import time
from datetime import datetime
from urllib.parse import quote

from config import settings

PYTHON = settings.ROOT_DIR / ".venv-hindsight" / "Scripts" / "python.exe"
SERVIDOR = settings.ROOT_DIR / "servicios" / "hindsight_servidor.py"
REGISTRO = settings.DATA_DIR / "hindsight.log"
TIEMPO_RECORDAR = 1.5
MAX_GUARDADO = 1500

_proceso: subprocess.Popen | None = None
_listo = threading.Event()
_cola: queue.Queue = queue.Queue(maxsize=200)
_trabajador: threading.Thread | None = None


def url() -> str:
    return f"http://127.0.0.1:{settings.HINDSIGHT_PUERTO}"


def _banco() -> str:
    return f"{url()}/v1/default/banks/{quote(settings.HINDSIGHT_BANCO, safe='')}"


def instalado() -> bool:
    return PYTHON.exists() and SERVIDOR.exists()


def activo() -> bool:
    return _listo.is_set()


def _responde() -> bool:
    import httpx
    try:
        return httpx.get(f"{url()}/health", timeout=1.0).status_code == 200
    except Exception:
        return False


def iniciar() -> str:
    """Lanza el servidor (si no hay uno ya) y espera en segundo plano a que esté listo."""
    global _proceso
    if not settings.HINDSIGHT:
        return "Hindsight desactivado (ASSISTANT_HINDSIGHT=0)."
    if not instalado():
        return "Hindsight no está instalado (falta .venv-hindsight); la memoria de siempre sigue funcionando."
    if _responde():
        _listo.set()
        _arrancar_trabajador()
        return "Memoria Hindsight conectada."
    import os
    REGISTRO.parent.mkdir(parents=True, exist_ok=True)
    modelo = settings.HINDSIGHT_MODELO or settings.MODEL_LOCAL
    salida = REGISTRO.open("a", encoding="utf-8")
    _proceso = subprocess.Popen(
        [str(PYTHON), str(SERVIDOR), "--puerto", str(settings.HINDSIGHT_PUERTO), "--modelo", modelo,
         "--ollama", settings.LOCAL_BASE_URL, "--padre", str(os.getpid())],
        cwd=str(settings.ROOT_DIR), stdout=salida, stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    threading.Thread(target=_esperar_listo, name="hindsight-arranque", daemon=True).start()
    return f"Memoria Hindsight arrancando con {modelo} (tarda ~15 s; la primera vez, unos minutos)."


def _esperar_listo(limite: float = 900.0) -> None:
    inicio = time.monotonic()
    while time.monotonic() - inicio < limite:
        if _proceso is not None and _proceso.poll() is not None:
            return   # se cerró: ver data/hindsight.log
        if _responde():
            _listo.set()
            _arrancar_trabajador()
            return
        time.sleep(2)


def detener() -> None:
    global _proceso
    _listo.clear()
    if _proceso is not None and _proceso.poll() is None:
        _proceso.terminate()
        try:
            _proceso.wait(timeout=15)
        except subprocess.TimeoutExpired:
            _proceso.kill()
    _proceso = None


def recordar(pregunta: str, max_resultados: int = 5) -> str:
    """Recuerdos relacionados con la pregunta, como texto; "" si no hay o Hindsight no está."""
    if not activo() or not (pregunta or "").strip():
        return ""
    import httpx
    try:
        respuesta = httpx.post(f"{_banco()}/memories/recall", timeout=TIEMPO_RECORDAR,
                               json={"query": pregunta[:500], "max_tokens": 600})
        respuesta.raise_for_status()
        resultados = respuesta.json().get("results") or []
    except Exception:
        return ""
    lineas = []
    for item in resultados[:max_resultados]:
        texto = (item.get("text") or "").split(" | Involving:")[0].strip()
        if texto:
            lineas.append(f"- {texto}")
    return "\n".join(lineas)


def guardar_turno(pregunta: str, respuesta: str, origen: str = "consola") -> None:
    """Encola la conversación para guardarla sin hacer esperar al usuario."""
    if not activo() or not (pregunta or "").strip():
        return
    contenido = f"{settings.USER_NAME} dijo: {pregunta.strip()}\nEl asistente respondió: {(respuesta or '').strip()}"
    try:
        _cola.put_nowait({"content": contenido[:MAX_GUARDADO], "context": f"conversación por {origen}",
                          "timestamp": datetime.now().astimezone().isoformat(timespec="seconds")})
    except queue.Full:
        pass


def _arrancar_trabajador() -> None:
    global _trabajador
    if _trabajador is None or not _trabajador.is_alive():
        _trabajador = threading.Thread(target=_guardar_en_cola, name="hindsight-guardar", daemon=True)
        _trabajador.start()


def _guardar_en_cola() -> None:
    import httpx
    while True:
        item = _cola.get()
        if item is None:
            return
        try:
            httpx.post(f"{_banco()}/memories", json={"items": [item]}, timeout=180)
        except Exception:
            pass
