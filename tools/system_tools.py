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
    path = Path(ruta).expanduser().resolve()
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
