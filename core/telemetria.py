"""Uso de CPU, RAM y GPU para el HUD del avatar, medido en segundo plano y guardado en caché.

nvidia-smi tarda ~100 ms, así que no se llama en cada petición: un hilo lo mide cada 2 s
y las interfaces leen el último valor al instante.
"""
from __future__ import annotations

import shutil
import subprocess
import threading
import time

CADA = 2.0
_datos = {"cpu": 0.0, "ram": 0.0, "gpu": None, "vram": None, "temp": None, "hora": 0.0}
_lock = threading.Lock()
_hilo: threading.Thread | None = None


def _gpu() -> tuple[float, float, float] | None:
    ejecutable = shutil.which("nvidia-smi.exe") or shutil.which("nvidia-smi")
    if not ejecutable:
        return None
    try:
        salida = subprocess.run(
            [ejecutable, "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
             "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=3, check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip().splitlines()[0]
        uso, usada, total, temp = [float(v) for v in salida.split(",")]
        return uso, 100 * usada / max(total, 1), temp
    except Exception:
        return None


def medir() -> dict:
    import psutil
    gpu = _gpu()
    nuevos = {"cpu": psutil.cpu_percent(interval=None), "ram": psutil.virtual_memory().percent,
              "gpu": gpu[0] if gpu else None, "vram": round(gpu[1], 1) if gpu else None,
              "temp": gpu[2] if gpu else None, "hora": time.time()}
    with _lock:
        _datos.update(nuevos)
    return dict(nuevos)


def actual() -> dict:
    """Último valor medido (arranca el medidor la primera vez)."""
    global _hilo
    if _hilo is None or not _hilo.is_alive():
        def bucle() -> None:
            while True:
                try:
                    medir()
                except Exception:
                    pass
                time.sleep(CADA)
        _hilo = threading.Thread(target=bucle, name="telemetria", daemon=True)
        _hilo.start()
    with _lock:
        return dict(_datos)
