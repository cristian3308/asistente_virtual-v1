"""Limpia lo que dices antes de interpretarlo, como hacen los asistentes de voz.

Whisper escribe con puntuación ("Jarvis, abre Chrome.", "Abre, Chrome.") y a veces
empiezas llamándolo ("Oye Jarvis…"). Las órdenes directas y las preguntas sobre la
memoria comparan patrones, así que aquí se quita el llamado y la puntuación que no
cambia el significado. El modelo recibe la frase limpia pero completa.
"""
from __future__ import annotations

import re

_NOMBRES = r"(?:jarvis|yarvis|harvis|j[aá]rvis|asistente)"
# "Oye Jarvis," / "Ok Jarvis" / "Jarvis," / "Oye," al principio de la frase.
_LLAMADO = re.compile(
    rf"^\s*(?:(?:oye|hey|ey|ok|okay|okey|hola)\s*[,.!¡]*\s*)?{_NOMBRES}\s*[,.:;!¡]+\s*"
    rf"|^\s*(?:oye|hey|ey|ok|okay|okey)\s*[,.!¡]*\s*{_NOMBRES}\b\s*[,.:;!¡]*\s*"
    rf"|^\s*{_NOMBRES}\s+(?!(?:es|fue|era|significa|se\s+llama)\b)"
    r"|^\s*(?:oye|hey|ey)\s*[,.!¡]+\s*",
    re.IGNORECASE,
)


def normalizar(texto: str) -> str:
    """Quita el llamado inicial y la puntuación sobrante de los extremos; conserva las preguntas."""
    original = (texto or "").strip()
    limpio = _LLAMADO.sub("", original, count=1).strip()
    limpio = re.sub(r"^[\s,.;:!¡]+|[\s,.;:!¡]+$", "", limpio)   # "¿…?" se conserva
    limpio = re.sub(r"\s+", " ", limpio)
    if not limpio:
        return original
    return limpio[:1].upper() + limpio[1:] if limpio[:1].islower() and original[:1].isupper() else limpio


def para_comparar(texto: str) -> str:
    """Versión sin comas ni signos para reconocer órdenes: "Abre, Chrome." → "Abre Chrome"."""
    sin_signos = re.sub(r"[,;:.!¡¿?\"“”]+", " ", normalizar(texto))
    return re.sub(r"\s+", " ", sin_signos).strip()
