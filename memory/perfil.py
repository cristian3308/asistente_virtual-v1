"""Memoria personal estructurada: hechos sobre el usuario que se recuerdan siempre.

Los hechos se detectan de forma determinista en lo que dice el usuario ("me llamo…",
"mi mamá se llama…", "me gusta…", "recuerda que…"), sin depender de que el modelo
decida guardarlos. Cada hecho guarda fuente, fecha, confianza y vigencia; al
corregirse, el valor anterior queda como histórico (vigente = 0) en vez de borrarse.
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from datetime import datetime, timezone

from config.settings import DATA_DIR

DB_PATH = DATA_DIR / "perfil.db"

_RELACIONES = ("mamá", "mama", "madre", "papá", "papa", "padre", "hermano", "hermana", "esposa", "esposo",
               "novia", "novio", "hijo", "hija", "abuela", "abuelo", "tío", "tio", "tía", "tia", "primo", "prima",
               "mejor amigo", "mejor amiga", "perro", "perra", "gato", "gata", "jefe", "jefa", "pareja")
_NORMALIZA_RELACION = {"mama": "mamá", "madre": "mamá", "papa": "papá", "padre": "papá", "tio": "tío", "tia": "tía"}
_NOMBRE = r"([A-ZÁÉÍÓÚÑ][\wáéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][\wáéíóúñ]+){0,3})"
_FIN = r"(?=\s*(?:[,.;!?]|\s+y\s+|$))"


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sin_acentos(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()


def _conectar() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conexion = sqlite3.connect(DB_PATH)
    conexion.execute(
        """CREATE TABLE IF NOT EXISTS hechos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clave TEXT NOT NULL,          -- p. ej. nombre, mamá, gusto, nota
            valor TEXT NOT NULL,
            categoria TEXT NOT NULL,      -- identidad, familia, gustos, trabajo, lugar, nota
            fuente TEXT NOT NULL,         -- frase original del usuario
            confianza REAL NOT NULL,      -- 1.0 confirmado por el usuario
            vigente INTEGER NOT NULL DEFAULT 1,
            creado TEXT NOT NULL,
            actualizado TEXT NOT NULL
        )"""
    )
    return conexion


# Claves de valor único: un nuevo valor reemplaza al anterior (que queda como histórico).
_UNICAS = {"nombre", "apodo", "edad", "cumpleaños", "ciudad", "trabajo", "estudios"} | {
    _NORMALIZA_RELACION.get(r, r) for r in _RELACIONES if r not in ("hermano", "hermana", "hijo", "hija",
                                                                       "primo", "prima", "perro", "gato")}


def extraer_hechos(texto: str) -> list[tuple[str, str, str]]:
    """Devuelve [(clave, valor, categoria)] con los datos personales que el usuario afirma."""
    hechos: list[tuple[str, str, str]] = []
    t = " " + texto.strip() + " "

    for clave, patron in (("nombre", r"\b[Mm]e llamo\s+"), ("nombre", r"\b[Mm]i nombre es\s+"), ("apodo", r"\b[Ll]l[aá]mame\s+")):
        if m := re.search(patron + _NOMBRE + _FIN, t):
            hechos.append((clave, m.group(1), "identidad"))
    relaciones = "|".join(sorted((re.escape(r) for r in _RELACIONES), key=len, reverse=True))
    for m in re.finditer(rf"\bmi\s+({relaciones})\s+se\s+llama\s+{_NOMBRE}{_FIN}", t, re.IGNORECASE):
        relacion = m.group(1).lower()
        hechos.append((_NORMALIZA_RELACION.get(relacion, relacion), m.group(2), "familia"))
    for m in re.finditer(r"\b(no\s+)?me\s+(?:gusta|gustan|encanta|encantan)\s+(?:mucho\s+)?([^.,;!?]{2,60})", t, re.IGNORECASE):
        hechos.append(("no le gusta" if m.group(1) else "le gusta", m.group(2).strip(), "gustos"))
    if m := re.search(r"\bprefiero\s+([^.,;!?]{2,60})", t, re.IGNORECASE):
        hechos.append(("prefiere", m.group(1).strip(), "gustos"))
    if m := re.search(r"\btengo\s+(\d{1,3})\s+años\b", t, re.IGNORECASE):
        hechos.append(("edad", m.group(1), "identidad"))
    if m := re.search(r"\bvivo\s+en\s+([^.,;!?]{2,50})", t, re.IGNORECASE):
        hechos.append(("ciudad", m.group(1).strip(), "lugar"))
    if m := re.search(r"\btrabajo\s+(?:en|como|de)\s+([^.,;!?]{2,60})", t, re.IGNORECASE):
        hechos.append(("trabajo", m.group(1).strip(), "trabajo"))
    if m := re.search(r"\bestudio\s+([^.,;!?]{2,60})", t, re.IGNORECASE):
        hechos.append(("estudios", m.group(1).strip(), "trabajo"))
    if m := re.search(r"\bmi\s+cumplea[nñ]os\s+es\s+(?:el\s+)?([^.,;!?]{3,40})", t, re.IGNORECASE):
        hechos.append(("cumpleaños", m.group(1).strip(), "identidad"))
    if m := re.search(r"\b(?:recuerda|recuérdate|guarda|anota)\s+(?:que|esto:?)\s+(.{3,240})", t, re.IGNORECASE):
        hechos.append(("nota", m.group(1).strip(" .!"), "nota"))
    hechos.extend(("regla", regla, "regla_operativa") for regla in extraer_reglas(texto))
    return hechos


# Verbos en imperativo/subjuntivo: "siempre respóndeme…", "nunca uses…". Evita guardar
# frases descriptivas como "siempre me pasa que…".
_ORDEN = (r"(?:resp[oó]nd\w*|cont[eé]st\w*|h[aá]bl\w*|[uú]sa\w*|uses|di|digas|d[ií]me|ll[aá]m\w+|"
          r"pregunt\w*|guard\w*|[aá]br\w*|escr[ií]b\w*|p[oó]n\w*|tr[aá]t\w*|av[ií]s\w*|haz|hagas|m[aá]nd\w*|"
          r"env[ií]\w*|mu[eé]str\w*|incl[uú]y\w*|ev[ií]t\w*|confirm\w*|ejec[uú]t\w*|res[uú]m\w*|expl[ií]c\w*)")


def extraer_reglas(texto: str) -> list[str]:
    """Instrucciones permanentes de comportamiento que el usuario le da al asistente."""
    if "?" in texto or texto.strip().startswith("¿"):
        return []  # una pregunta ("¿siempre usas la nube?") no es una orden
    t = " " + texto.strip() + " "
    reglas = []
    if m := re.search(r"\bcuando\s+te\s+(?:pida|diga|pregunte|hable)\s+(.{2,80}?),\s*(?:siempre\s+)?(.{3,160}?)[.!]?\s*$", t, re.IGNORECASE):
        reglas.append(f"Cuando te pida {m.group(1).strip()}: {m.group(2).strip()}")
    if m := re.search(r"\bno\s+uses\s+(.{2,60}?),\s*(?:mejor\s+)?usa\s+(.{2,80}?)[.!]?\s*$", t, re.IGNORECASE):
        reglas.append(f"No uses {m.group(1).strip()}; usa {m.group(2).strip()}")
    if m := re.search(r"\b(?:de\s+ahora\s+en\s+adelante|a\s+partir\s+de\s+ahora|desde\s+ahora)\s*,?\s+(.{3,180}?)[.!]?\s*$", t, re.IGNORECASE):
        reglas.append(m.group(1).strip()[:1].upper() + m.group(1).strip()[1:])
    elif m := re.search(rf"\b(siempre|nunca|jamás)\s+((?:me\s+)?{_ORDEN}\b.{{2,160}}?)[.!]?\s*$", t, re.IGNORECASE):
        reglas.append(f"{m.group(1).capitalize()} {m.group(2).strip()}")
    return reglas


def guardar(clave: str, valor: str, categoria: str, fuente: str, confianza: float = 1.0) -> bool:
    """Guarda un hecho. Devuelve False si ya existía igual (no duplica)."""
    clave, valor = clave.strip().lower(), valor.strip()
    if not clave or not valor:
        return False
    with _conectar() as db:
        existe = db.execute("SELECT 1 FROM hechos WHERE clave=? AND lower(valor)=lower(?) AND vigente=1",
                            (clave, valor)).fetchone()
        if existe:
            return False
        if clave in _UNICAS:
            db.execute("UPDATE hechos SET vigente=0, actualizado=? WHERE clave=? AND vigente=1", (_ahora(), clave))
        db.execute("INSERT INTO hechos(clave, valor, categoria, fuente, confianza, vigente, creado, actualizado) "
                   "VALUES (?, ?, ?, ?, ?, 1, ?, ?)", (clave, valor, categoria, fuente[:500], confianza, _ahora(), _ahora()))
    return True


def aprender_de(texto: str) -> list[str]:
    """Extrae y guarda los hechos de una frase del usuario; devuelve descripciones de lo nuevo."""
    nuevos = []
    for clave, valor, categoria in extraer_hechos(texto):
        if guardar(clave, valor, categoria, texto):
            nuevos.append(f"{clave}: {valor}")
    return nuevos


def hechos(incluir_historicos: bool = False) -> list[dict]:
    consulta = "SELECT id, clave, valor, categoria, confianza, vigente, actualizado FROM hechos"
    if not incluir_historicos:
        consulta += " WHERE vigente=1"
    with _conectar() as db:
        filas = db.execute(consulta + " ORDER BY categoria, id").fetchall()
    return [dict(zip(("id", "clave", "valor", "categoria", "confianza", "vigente", "actualizado"), f)) for f in filas]


def olvidar(texto: str) -> int:
    """Marca como no vigentes los hechos cuyo id, clave o valor coincide con el texto."""
    texto = texto.strip()
    if not texto:
        return 0
    with _conectar() as db:
        if texto.isdigit():
            cursor = db.execute("UPDATE hechos SET vigente=0, actualizado=? WHERE id=? AND vigente=1", (_ahora(), int(texto)))
        else:
            # "olvida que me gusta el café": el dato guardado ("el café") aparece dentro de la frase.
            patron = f"%{texto.lower()}%"
            cursor = db.execute("UPDATE hechos SET vigente=0, actualizado=? WHERE vigente=1 AND "
                                "(lower(clave) LIKE ? OR lower(valor) LIKE ? OR instr(?, lower(valor)) > 0)",
                                (_ahora(), patron, patron, texto.lower()))
        return cursor.rowcount


def asegurar_nombre(nombre: str) -> None:
    """El nombre configurado del dueño cuenta como hecho base si aún no hay otro."""
    with _conectar() as db:
        if not db.execute("SELECT 1 FROM hechos WHERE clave='nombre' AND vigente=1").fetchone():
            db.execute("INSERT INTO hechos(clave, valor, categoria, fuente, confianza, vigente, creado, actualizado) "
                       "VALUES ('nombre', ?, 'identidad', 'configuración', 1.0, 1, ?, ?)", (nombre, _ahora(), _ahora()))


def reglas_para_modelo(max_chars: int = 600) -> str:
    """Reglas de comportamiento que el usuario ha dado; se inyectan como instrucciones permanentes."""
    texto = "\n".join(f"- {h['valor']}" for h in hechos() if h["categoria"] == "regla_operativa")
    return texto[:max_chars]


def resumen_para_modelo(max_chars: int = 700) -> str:
    """Texto compacto con lo que se sabe del usuario, para incluir en cada respuesta."""
    lineas = [f"- {h['clave']}: {h['valor']}" for h in hechos() if h["categoria"] != "regla_operativa"]
    texto = "\n".join(lineas)
    return texto if len(texto) <= max_chars else texto[:max_chars].rsplit("\n", 1)[0] + "\n- (…más datos guardados)"
