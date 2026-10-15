"""Abre aplicaciones de Windows buscando automáticamente su ubicación."""
from __future__ import annotations

import os
import shutil
from pathlib import Path


def _normalizar(valor: str) -> str:
    return "".join(char.lower() for char in valor if char.isalnum())


def _buscar_candidatos(nombre: str) -> list[Path]:
    consulta = _normalizar(Path(nombre).stem)
    if not consulta:
        return []
    candidatos: list[Path] = []

    # Primero intenta comandos disponibles en PATH: chrome, notepad, code, etc.
    for variante in (nombre, f"{nombre}.exe"):
        encontrado = shutil.which(variante)
        if encontrado:
            return [Path(encontrado)]

    variables = {
        "APPDATA": os.getenv("APPDATA", ""),
        "PROGRAMFILES": os.getenv("ProgramFiles", ""),
        "PROGRAMFILES_X86": os.getenv("ProgramFiles(x86)", ""),
        "LOCALAPPDATA": os.getenv("LOCALAPPDATA", ""),
    }
    roots = [
        Path(variables["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
        Path(os.getenv("ProgramData", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
        Path(variables["PROGRAMFILES"]),
        Path(variables["PROGRAMFILES_X86"]),
        Path(variables["LOCALAPPDATA"]) / "Programs",
    ]
    for root in roots:
        if not root.is_dir():
            continue
        try:
            # Limita el recorrido para no bloquear la consola en discos grandes.
            for item in root.rglob("*"):
                if len(candidatos) >= 12:
                    break
                if item.is_file() and item.suffix.lower() in {".exe", ".lnk", ".bat"}:
                    stem = _normalizar(item.stem)
                    if stem and (consulta == stem or consulta in stem or (len(stem) >= 3 and stem in consulta)):
                        candidatos.append(item)
        except (OSError, RuntimeError):
            continue
    # Mantiene orden y elimina duplicados.
    return list(dict.fromkeys(candidatos))


def abrir_aplicacion(
    nombre_aplicacion: str = "",
    aplicacion: str = "",
    app: str = "",
    ruta_archivo: str = "",
    path: str = "",
    file_path: str = "",
    **kwargs,
) -> str:
    """Abre una app por nombre; también acepta una ruta explícita como respaldo."""
    consulta = nombre_aplicacion or aplicacion or app
    explicit_path = file_path or ruta_archivo
    if explicit_path:
        candidate = Path(explicit_path).expanduser()
        if not candidate.is_absolute() and path:
            candidate = Path(path).expanduser() / candidate
        if not candidate.exists():
            return f"No encontré la aplicación en la ruta indicada: {candidate}"
        candidates = [candidate]
    else:
        candidates = _buscar_candidatos(consulta)
    if not candidates:
        return f"No encontré '{consulta}'. Prueba con el nombre visible de la aplicación o proporciona su ruta."
    selected = candidates[0]
    try:
        os.startfile(str(selected))
        extra = ""
        if len(candidates) > 1:
            extra = " Otras coincidencias: " + ", ".join(str(item) for item in candidates[1:4])
        return f"Aplicación abierta: {selected}{extra}"
    except OSError as exc:
        return f"Encontré '{selected}', pero Windows no pudo abrirla: {exc}"
