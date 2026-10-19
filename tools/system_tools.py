"""Herramientas locales de sistema para Windows."""
from __future__ import annotations

import shutil
import subprocess
import platform
from pathlib import Path

import psutil
from config import settings


def estado_hardware() -> str:
    cpu = psutil.cpu_percent(interval=0.3)
    ram = psutil.virtual_memory()
    disk_root = Path.home().anchor or "C:\\"
    try:
        disk = psutil.disk_usage(disk_root)
        disk_text = f"Disco {disk_root}: {disk.free / 1024**3:.1f} GB libres de {disk.total / 1024**3:.1f} GB"
    except OSError:
        disk_text = "Disco: información no disponible"
    gpu = "nvidia-smi no disponible"
    nvidia = shutil.which("nvidia-smi.exe") or shutil.which("nvidia-smi")
    if nvidia:
        try:
            out = subprocess.run(
                [nvidia, "--query-gpu=name,memory.used,memory.total,utilization.gpu,temperature.gpu", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=3, check=True,
            ).stdout.strip()
            gpu = out or gpu
        except (OSError, subprocess.SubprocessError):
            gpu = "No se pudo consultar nvidia-smi"
    return (
        f"CPU ({platform.processor() or platform.machine()}): {cpu:.0f}%\n"
        f"RAM: {ram.used / 1024**3:.1f} / {ram.total / 1024**3:.1f} GB ({ram.percent:.0f}%)\n"
        f"{disk_text}\nGPU: {gpu}"
    )


def listar_procesos_pesados() -> str:
    processes = []
    for proc in psutil.process_iter(["pid", "name", "memory_info"]):
        try:
            info = proc.info
            processes.append((info["memory_info"].rss / 1024**2, info["name"] or "?", info["pid"]))
        except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
            continue
    return "Top procesos por uso de RAM:\n" + "\n".join(
        f"- {name} (PID {pid}): {mem:.0f} MB" for mem, name, pid in sorted(processes, reverse=True)[:10]
    )


def explorar_directorio(ruta: str = ".") -> str:
    path = settings.resolver_ruta(ruta)
    if not settings.path_is_allowed(path):
        return "Acceso bloqueado: la carpeta está fuera de las rutas locales permitidas."
    if not path.is_dir():
        return f"No es un directorio accesible: {path}"
    try:
        items = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))[:80]
        return f"Contenido de {path}:\n" + "\n".join(
            f"{'[DIR]' if item.is_dir() else '[FILE]'} {item.name}" for item in items
        )
    except OSError as exc:
        return f"Error al leer directorio: {exc}"


_START_APPS_CACHE: tuple[float, list[dict]] | None = None


def aplicaciones_menu_inicio(max_age: float = 300.0) -> list[dict]:
    """Apps del menú Inicio (incluidas las de Microsoft Store) como [{"Name", "AppID"}]."""
    import json
    import time

    global _START_APPS_CACHE
    if _START_APPS_CACHE and time.monotonic() - _START_APPS_CACHE[0] < max_age:
        return _START_APPS_CACHE[1]
    # Comando fijo de solo lectura; no acepta texto del usuario ni del modelo.
    command = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-StartApps | ConvertTo-Json -Compress"
    try:
        out = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                             capture_output=True, timeout=30, check=True).stdout.decode("utf-8", errors="replace")
        data = json.loads(out or "[]")
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    apps = [item for item in (data if isinstance(data, list) else [data]) if item.get("Name") and item.get("AppID")]
    _START_APPS_CACHE = (time.monotonic(), apps)
    return apps


def _normalizar_nombre(value: str) -> str:
    import unicodedata
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return "".join(char.lower() for char in value if char.isalnum())


def listar_aplicaciones(filtro: str = "") -> str:
    """Lista las aplicaciones instaladas que aparecen en el menú Inicio, opcionalmente filtradas."""
    apps = aplicaciones_menu_inicio()
    if not apps:
        return "No pude obtener la lista de aplicaciones (Get-StartApps no respondió)."
    query = _normalizar_nombre(filtro)
    names = sorted({app["Name"] for app in apps if not query or query in _normalizar_nombre(app["Name"])}, key=str.lower)
    if not names:
        return f"No hay ninguna aplicación instalada que coincida con '{filtro}'."
    shown = names[:80]
    extra = f"\n… y {len(names) - len(shown)} más (usa un filtro)." if len(names) > len(shown) else ""
    header = f"Aplicaciones que coinciden con '{filtro}'" if query else "Aplicaciones instaladas"
    return f"{header} ({len(names)}):\n- " + "\n- ".join(shown) + extra


# --- Ventana en primer plano -------------------------------------------------
# Al preguntar "¿por qué me da este error?" la ventana activa es la consola del propio
# asistente; por eso se recuerda en qué ventana estabas antes (solo título y programa).
_PROPIAS = {"windowsterminal.exe", "powershell.exe", "pwsh.exe", "cmd.exe", "conhost.exe", "python.exe",
            "electron.exe", "openconsole.exe"}
_ventanas_recientes: list[tuple[str, str]] = []
_vigilando = False


def _ventana_en_primer_plano() -> tuple[str, str]:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return "", ""
    largo = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(largo + 1)
    user32.GetWindowTextW(hwnd, buffer, largo + 1)
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    try:
        programa = psutil.Process(pid.value).name()
    except (psutil.Error, ValueError):
        programa = "?"
    return buffer.value, programa


def iniciar_vigilancia_ventanas(intervalo: float = 1.0) -> None:
    """Hilo ligero que recuerda las últimas ventanas (no propias) en las que estuviste."""
    global _vigilando
    if _vigilando:
        return
    _vigilando = True

    def vigilar() -> None:
        import time
        while True:
            try:
                titulo, programa = _ventana_en_primer_plano()
                if titulo and programa.lower() not in _PROPIAS and (not _ventanas_recientes or _ventanas_recientes[-1] != (titulo, programa)):
                    _ventanas_recientes.append((titulo, programa))
                    del _ventanas_recientes[:-5]
            except Exception:
                pass
            time.sleep(intervalo)

    import threading
    threading.Thread(target=vigilar, name="vigilancia-ventanas", daemon=True).start()


def ventana_activa() -> str:
    """Qué ventana tienes delante y en cuál estabas antes de hablarle al asistente."""
    try:
        titulo, programa = _ventana_en_primer_plano()
    except Exception as exc:
        return f"No pude consultar la ventana activa: {exc}"
    lineas = [f"Ventana en primer plano: «{titulo or '(sin título)'}» ({programa})"]
    anteriores = [v for v in _ventanas_recientes if v != (titulo, programa)]
    if anteriores:
        ultimo_titulo, ultimo_programa = anteriores[-1]
        lineas.append(f"Antes de escribirme estabas en: «{ultimo_titulo}» ({ultimo_programa})")
    return "\n".join(lineas)
