"""Memoria procedimental: recetas de herramientas que funcionaron, para repetirlas a la primera.

Cuando un turno resuelve algo encadenando dos o más herramientas sin errores, se guarda la
secuencia (objetivo → pasos). Antes de cada respuesta se busca una receta parecida y se le
pasa al modelo como guía. Las recetas acumulan éxitos y fallos; una receta que falla más de
lo que acierta deja de sugerirse.
"""
from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from datetime import datetime

from config.settings import DATA_DIR

DB_PATH = DATA_DIR / "procedimientos.db"
SIMILITUD_MINIMA = 0.4
_VACIAS = {"que", "como", "para", "por", "con", "los", "las", "una", "uno", "del", "mis", "tus", "este", "esta",
           "esto", "ese", "eso", "hay", "puedes", "podrias", "favor", "porfa", "quiero", "dame", "dime", "hazme"}


def _raices(texto: str) -> set[str]:
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    return {p[:5] for p in re.findall(r"[a-z0-9]{3,}", texto) if p not in _VACIAS}


def _similitud(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _conectar() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute(
        """CREATE TABLE IF NOT EXISTS procedimientos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            objetivo TEXT NOT NULL,
            raices TEXT NOT NULL,
            pasos TEXT NOT NULL,          -- [{"herramienta": ..., "argumentos": {...}}]
            exitos INTEGER NOT NULL DEFAULT 1,
            fallos INTEGER NOT NULL DEFAULT 0,
            creado TEXT NOT NULL,
            usado TEXT NOT NULL
        )"""
    )
    return db


def registrar(objetivo: str, pasos: list[tuple[str, dict]]) -> int | None:
    """Guarda (o refuerza) la receta de un turno exitoso con 2+ herramientas distintas."""
    if len({nombre for nombre, _ in pasos}) < 2:
        return None
    raices = _raices(objetivo)
    secuencia = [n for n, _ in pasos]
    ahora = datetime.now().isoformat(timespec="seconds")
    with _conectar() as db:
        for fila in db.execute("SELECT id, raices, pasos FROM procedimientos").fetchall():
            if (_similitud(raices, set(fila["raices"].split())) >= 0.6
                    and [p["herramienta"] for p in json.loads(fila["pasos"])] == secuencia):
                db.execute("UPDATE procedimientos SET exitos = exitos + 1, usado = ? WHERE id = ?", (ahora, fila["id"]))
                return fila["id"]
        cursor = db.execute(
            "INSERT INTO procedimientos(objetivo, raices, pasos, creado, usado) VALUES (?, ?, ?, ?, ?)",
            (objetivo[:300], " ".join(sorted(raices)),
             json.dumps([{"herramienta": n, "argumentos": a} for n, a in pasos], ensure_ascii=False), ahora, ahora))
        return cursor.lastrowid


def buscar(objetivo: str) -> dict | None:
    """La receta más parecida que funciona más de lo que falla, o None."""
    raices = _raices(objetivo)
    mejor, puntuacion = None, SIMILITUD_MINIMA
    with _conectar() as db:
        for fila in db.execute("SELECT * FROM procedimientos WHERE exitos > fallos").fetchall():
            similitud = _similitud(raices, set(fila["raices"].split()))
            if similitud >= puntuacion:
                mejor, puntuacion = dict(fila), similitud
    return mejor


def marcar_fallo(id_procedimiento: int) -> None:
    with _conectar() as db:
        db.execute("UPDATE procedimientos SET fallos = fallos + 1 WHERE id = ?", (id_procedimiento,))


def guia_para_modelo(objetivo: str) -> str:
    receta = buscar(objetivo)
    if not receta:
        return ""
    pasos = json.loads(receta["pasos"])
    lineas = [f"{i}. {p['herramienta']}({json.dumps(p['argumentos'], ensure_ascii=False)[:120]})"
              for i, p in enumerate(pasos, 1)]
    return (f"Para algo parecido («{receta['objetivo'][:100]}») funcionó antes esta secuencia "
            f"({receta['exitos']} vez/veces). Úsala como guía, adaptando los argumentos:\n" + "\n".join(lineas))


def listar(limite: int = 20) -> list[dict]:
    with _conectar() as db:
        return [dict(f) for f in db.execute(
            "SELECT * FROM procedimientos ORDER BY exitos DESC, usado DESC LIMIT ?", (limite,)).fetchall()]
