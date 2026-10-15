"""Herramientas de auditoría y ejecución segura para Windows."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import psutil
from rich.prompt import Confirm
from config import settings
from core.self_coder import confirmation_allowed


def auditar_puertos_locales() -> str:
    rows = []
    try:
        for conn in psutil.net_connections(kind="inet"):
            if conn.status != psutil.CONN_LISTEN or not conn.laddr:
                continue
            pid = conn.pid
            try:
                exe = psutil.Process(pid).name() if pid else "desconocido"
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                exe = "desconocido"
            rows.append(f"{conn.laddr.ip}\t{conn.laddr.port}\t{pid or '-'}\t{exe}")
    except (psutil.AccessDenied, OSError) as exc:
        return f"No se pudieron consultar todas las conexiones: {exc}"
    return "IP\tPuerto\tPID\tEjecutable\n" + ("\n".join(sorted(set(rows))) or "No se encontraron puertos LISTEN.")


def leer_codigo_fuente(ruta_archivo: str, linea_inicio: int = 1, linea_fin: int = 120) -> str:
    path = Path(ruta_archivo).expanduser().resolve()
    if not settings.path_is_allowed(path):
        return "Lectura bloqueada: el archivo está fuera de las rutas locales permitidas."
    if path.name.lower().startswith(".env") or path.suffix.lower() in {".pem", ".key", ".p12", ".pfx"}:
        return "Lectura bloqueada: el archivo parece contener secretos o credenciales."
    if not path.is_file():
        return f"No existe el archivo: {path}"
    start, end = max(1, int(linea_inicio)), max(1, int(linea_fin))
    if end < start:
        return "linea_fin debe ser mayor o igual que linea_inicio."
    try:
        with path.open("r", encoding="utf-8", errors="replace") as file:
            lines = file.readlines()
        return "\n".join(f"{n:4}: {lines[n-1].rstrip()}" for n in range(start, min(end, len(lines)) + 1)) or "(rango vacío)"
    except OSError as exc:
        return f"No se pudo leer el archivo: {exc}"


def estado_git(ruta_repositorio: str = ".") -> str:
    path = Path(ruta_repositorio).expanduser().resolve()
    if not path.is_dir():
        return f"No existe el directorio: {path}"
    outputs = []
    for args in (["git", "status", "-s"], ["git", "log", "-n", "5", "--oneline"]):
        try:
            result = subprocess.run(args, cwd=path, shell=False, capture_output=True, text=True, timeout=10)
            outputs.append(result.stdout.strip() if result.returncode == 0 else result.stderr.strip())
        except (OSError, subprocess.SubprocessError) as exc:
            outputs.append(str(exc))
    return f"git status -s:\n{outputs[0] or '(limpio)'}\n\ngit log:\n{outputs[1] or '(sin commits)'}"


_SAFE_EXACT = re.compile(
    r"^(?:Get-Process|Get-Service|Get-NetTCPConnection|ipconfig(?: /all)?|whoami(?: /all)?|"
    r"git status(?: -s)?|pip list|dir)$",
    re.IGNORECASE,
)
_BLOCKED = re.compile(
    r"Remove-Item\b[^\r\n]*(?:-Recurse|\-Force)|\bdel\s+/f\s+/s\b|\bFormat-Volume\b|\bStop-Computer\b",
    re.IGNORECASE,
)


def ejecutar_powershell_seguro(comando: str) -> str:
    command = comando.strip()
    if not command:
        return "Comando vacío."
    if _BLOCKED.search(command):
        return "Bloqueado: comando destructivo no permitido."
    safe = bool(_SAFE_EXACT.fullmatch(command))
    if not safe:
        if not confirmation_allowed():
            return "Requiere consola local: PowerShell no se ejecuta desde Telegram."
        if not Confirm.ask(f"⚠️ ¿Autorizas ejecutar en PowerShell: {command}?", default=False):
            return "Ejecución cancelada."
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            shell=False, capture_output=True, text=True, timeout=30,
        )
        output = (result.stdout or result.stderr).strip()
        return output[:12000] or f"PowerShell terminó con código {result.returncode} sin salida."
    except (OSError, subprocess.SubprocessError) as exc:
        return f"Error al ejecutar PowerShell: {exc}"
