"""Seguridad a la voz: qué está expuesto en tu red y cerrar un proceso (con tu confirmación)."""
from __future__ import annotations

import os

# Procesos que nunca se cierran: tumbarían Windows o al propio asistente.
_INTOCABLES = {"system", "system idle process", "csrss.exe", "wininit.exe", "winlogon.exe", "services.exe",
               "lsass.exe", "smss.exe", "svchost.exe", "dwm.exe", "explorer.exe", "fontdrvhost.exe", "registry",
               "memcompression", "secure system"}


def informe_seguridad_red() -> str:
    from core.sentinel import informe_exposicion
    return informe_exposicion()


def cerrar_proceso(pid: int | str) -> str:
    """Cierra un proceso por su PID, solo con confirmación en la consola del PC."""
    import psutil
    from core import auditoria
    from core.self_coder import confirmar, confirmation_allowed

    try:
        pid = int(str(pid).strip())
        proceso = psutil.Process(pid)
        nombre, ruta = proceso.name(), proceso.exe()
    except (ValueError, psutil.NoSuchProcess):
        return f"No hay ningún proceso con PID {pid}."
    except psutil.AccessDenied:
        return f"Windows no me deja ver el proceso {pid} (es del sistema o de otro usuario)."
    if pid in (os.getpid(), os.getppid()) or nombre.lower() in _INTOCABLES or pid <= 4:
        return f"No cierro {nombre}: es parte de Windows o del propio asistente."
    if not confirmation_allowed():
        return f"Para cerrar {nombre} (PID {pid}) necesito tu confirmación en la consola del PC."
    if not confirmar(f"¿Cerrar {nombre} (PID {pid}) — {ruta}?"):
        return "No lo cerré."
    try:
        proceso.terminate()
        proceso.wait(timeout=5)
    except psutil.TimeoutExpired:
        proceso.kill()
    except psutil.NoSuchProcess:
        pass
    except psutil.AccessDenied:
        return f"Windows no me dejó cerrar {nombre}: hace falta ejecutarlo como administrador."
    auditoria.registrar("seguridad", "cerrar proceso", f"{nombre} ({pid})", ruta)
    return f"Hecho. Cerré {nombre} (PID {pid})."
