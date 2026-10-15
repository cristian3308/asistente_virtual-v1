"""Abre aplicaciones de Windows buscando automáticamente su ubicación."""
from __future__ import annotations

import os
import shutil
import time
import unicodedata
from pathlib import Path

_ALIASES = {
    "calculadora": "calc",
    "explorador": "explorer",
    "exploradordearchivos": "explorer",
    "blocdenotas": "notepad",
    "navegador": "chrome",
    "musica": "spotify",
    "terminal": "wt",
    "cmd": "cmd",
    "configuracion": "ms-settings:",
}


def _normalizar(valor: str) -> str:
    normalized = unicodedata.normalize("NFKD", valor).encode("ascii", "ignore").decode()
    return "".join(char.lower() for char in normalized if char.isalnum())


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
    start_menu_roots = [
        Path(value) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        for value in (variables["APPDATA"], os.getenv("ProgramData", "")) if value
    ]
    for root in start_menu_roots:
        if not root.is_dir():
            continue
        try:
            for item in root.rglob("*.lnk"):
                stem = _normalizar(item.stem)
                if stem == consulta:
                    return [item]
                if stem and (consulta in stem or (len(stem) >= 3 and stem in consulta)):
                    candidatos.append(item)
        except (OSError, RuntimeError):
            continue
    deadline = time.monotonic() + 8
    program_roots = [Path(value) for value in (
        variables["PROGRAMFILES"], variables["PROGRAMFILES_X86"]
    ) if value]
    if variables["LOCALAPPDATA"]:
        program_roots.append(Path(variables["LOCALAPPDATA"]) / "Programs")
    for root in program_roots:
        if time.monotonic() >= deadline or not root.is_dir():
            continue
        try:
            patterns = ("*.exe", "*/*.exe", "*/*/*.exe")
            for pattern in patterns:
                for item in root.glob(pattern):
                    if time.monotonic() >= deadline:
                        break
                    stem = _normalizar(item.stem)
                    if stem == consulta:
                        return [item]
                    if stem and (consulta in stem or (len(stem) >= 3 and stem in consulta)):
                        candidatos.append(item)
                if time.monotonic() >= deadline:
                    break
        except (OSError, RuntimeError):
            continue
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
    alias = _ALIASES.get(_normalizar(consulta), consulta)
    if alias == "ms-settings:":
        try:
            os.startfile(alias)
            return "Aplicación abierta: configuración de Windows"
        except OSError as exc:
            return f"No se pudo abrir configuración de Windows: {exc}"
    explicit_path = file_path or ruta_archivo
    if explicit_path:
        candidate = Path(explicit_path).expanduser()
        if not candidate.is_absolute() and path:
            candidate = Path(path).expanduser() / candidate
        if not candidate.exists():
            return f"No encontré la aplicación en la ruta indicada: {candidate}"
        candidates = [candidate]
    else:
        candidates = _buscar_candidatos(alias)
    if not candidates:
        return f"No encontré '{consulta}'. Prueba con el nombre visible de la aplicación o proporciona su ruta."
    normalized_alias = _normalizar(alias)
    exact = [candidate for candidate in candidates if _normalizar(candidate.stem) == normalized_alias]
    if len(exact) == 1:
        candidates = exact
    elif len(candidates) == 1 and normalized_alias in _normalizar(candidates[0].stem):
        candidates = candidates
    else:
        options = ", ".join(str(candidate) for candidate in candidates[:8])
        return f"Encontré coincidencias para '{consulta}', pero no una coincidencia exacta: {options}. ¿Cuál quieres abrir?"
    selected = candidates[0]
    try:
        os.startfile(str(selected))
        extra = ""
        if len(candidates) > 1:
            extra = " Otras coincidencias: " + ", ".join(str(item) for item in candidates[1:4])
        return f"Aplicación abierta: {selected}{extra}"
    except OSError as exc:
        return f"Encontré '{selected}', pero Windows no pudo abrirla: {exc}"
