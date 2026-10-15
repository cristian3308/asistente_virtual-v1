"""Notas Markdown compatibles con una bóveda Obsidian."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from config.settings import VAULT_PATH


def _safe_name(value: str) -> str:
    return re.sub(r"[^\w\- ]+", "", value, flags=re.UNICODE).strip() or "nota"


def crear_o_actualizar_nota(titulo: str, contenido: str, carpeta: str = "Proyectos", tags: str = "") -> str:
    folder = VAULT_PATH / _safe_name(carpeta)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{_safe_name(titulo)}.md"
    tag_line = " ".join(f"#{_safe_name(tag)}" for tag in tags.replace(",", " ").split() if tag.strip())
    text = f"# {titulo.strip()}\n\n*Actualizado: {datetime.now():%Y-%m-%d %H:%M}*\n\n{tag_line}\n\n{contenido.strip()}\n"
    path.write_text(text, encoding="utf-8")
    return f"Nota guardada: {path}"


def buscar_en_boveda(consulta: str) -> str:
    terms = [term.lower() for term in consulta.split() if term.strip()]
    results = []
    for path in VAULT_PATH.rglob("*.md") if VAULT_PATH.exists() else []:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            haystack = f"{path.name}\n{text}".lower()
            if all(term in haystack for term in terms):
                results.append(f"- {path}\n  {text[:500].replace(chr(10), ' ')}")
        except OSError:
            continue
    return "\n".join(results) or "No se encontraron notas."


def registrar_en_bitacora_diaria(nota: str) -> str:
    folder = VAULT_PATH / "Diario"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{datetime.now():%Y-%m-%d}.md"
    with path.open("a", encoding="utf-8") as file:
        file.write(f"\n- **{datetime.now():%H:%M:%S}** {nota.strip()}\n")
    return f"Bitácora actualizada: {path}"
