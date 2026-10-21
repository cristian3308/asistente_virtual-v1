"""Protocolos: una frase que prepara todo un escenario ("activa protocolo estudio").

Un protocolo es una lista de pasos con herramientas del asistente. Solo se permiten
herramientas inofensivas (sin cerrar programas, presionar botones ni ejecutar comandos),
porque al activarlo los pasos corren seguidos sin preguntar uno por uno. Los protocolos
que creas tú se guardan en data/protocolos.json después de que apruebes sus pasos.
"""
from __future__ import annotations

import json
import re
import unicodedata

from config import settings

ARCHIVO = settings.DATA_DIR / "protocolos.json"
PERMITIDAS = {
    "abrir_aplicacion": "abre una app (nombre_aplicacion)",
    "volumen": "volumen (accion: subir|bajar|silencio, o nivel 0-100)",
    "multimedia": "música (accion: pausa|siguiente|anterior|detener)",
    "organizar_ventana": "ventana (posicion: izquierda|derecha|maximizar|minimizar, app)",
    "programar_recordatorio": "recordatorio (mensaje, minutos)",
    "listar_tareas": "lee las tareas pendientes",
    "informe_seguridad_red": "programas expuestos en la red",
    "estado_hardware": "estado de CPU, RAM, disco y GPU",
    "listar_procesos_pesados": "procesos que más consumen",
    "leer_noticias_rss": "noticias de un canal RSS (url, cantidad)",
    "registrar_en_bitacora_diaria": "anota algo en el diario (nota)",
}

PREDETERMINADOS = {
    "estudio": {
        "descripcion": "Concentración: volumen bajo y pausa a los 50 minutos.",
        "pasos": [
            {"herramienta": "volumen", "argumentos": {"nivel": 30}},
            {"herramienta": "programar_recordatorio",
             "argumentos": {"mensaje": "Hora de una pausa de 10 minutos, señor. Estírate y toma agua.", "minutos": 50}},
            {"decir": "Protocolo estudio activado. Volumen al 30 % y te aviso en 50 minutos para descansar. A darle."},
        ],
    },
    "descanso": {
        "descripcion": "Pausa: detiene la música, repasa pendientes y avisa en 10 minutos.",
        "pasos": [
            {"herramienta": "multimedia", "argumentos": {"accion": "pausa"}},
            {"herramienta": "listar_tareas", "argumentos": {}},
            {"herramienta": "programar_recordatorio", "argumentos": {"mensaje": "Fin del descanso. ¿Seguimos?", "minutos": 10}},
            {"decir": "Protocolo descanso. Música en pausa; en 10 minutos te aviso para volver."},
        ],
    },
    "seguridad": {
        "descripcion": "Revisión: red expuesta, estado del PC y procesos pesados.",
        "pasos": [
            {"herramienta": "informe_seguridad_red", "argumentos": {}},
            {"herramienta": "estado_hardware", "argumentos": {}},
            {"herramienta": "listar_procesos_pesados", "argumentos": {}},
            {"decir": "Protocolo seguridad completado. Te dejo el informe en pantalla."},
        ],
    },
    "noche": {
        "descripcion": "Cierre del día: pendientes de mañana y volumen bajo.",
        "pasos": [
            {"herramienta": "listar_tareas", "argumentos": {}},
            {"herramienta": "volumen", "argumentos": {"nivel": 15}},
            {"decir": f"Buenas noches, {settings.USER_NAME}. Te dejo tus pendientes en pantalla. Descansa."},
        ],
    },
}


def _clave(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]", "", texto).strip()


def _propios() -> dict:
    try:
        return json.loads(ARCHIVO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def todos() -> dict:
    return {**PREDETERMINADOS, **_propios()}


def buscar(nombre: str) -> tuple[str, dict] | None:
    clave = _clave(nombre).removeprefix("protocolo ").removeprefix("modo ").strip()
    disponibles = todos()
    for nombre_p, protocolo in disponibles.items():
        if _clave(nombre_p) == clave:
            return nombre_p, protocolo
    for nombre_p, protocolo in disponibles.items():
        if clave and (clave in _clave(nombre_p) or _clave(nombre_p) in clave):
            return nombre_p, protocolo
    return None


def listar() -> str:
    lineas = [f"- {nombre}: {p.get('descripcion', '')}" for nombre, p in todos().items()]
    return "Protocolos disponibles (di «activa protocolo …»):\n" + "\n".join(lineas)


def validar(pasos: list) -> str | None:
    """Motivo por el que unos pasos no son aceptables, o None si están bien."""
    if not isinstance(pasos, list) or not pasos or len(pasos) > 12:
        return "Un protocolo necesita entre 1 y 12 pasos."
    for paso in pasos:
        if not isinstance(paso, dict):
            return "Cada paso debe ser un objeto."
        if "decir" in paso:
            if not isinstance(paso["decir"], str) or len(paso["decir"]) > 300:
                return "El texto a decir debe ser corto."
            continue
        if paso.get("herramienta") not in PERMITIDAS:
            return f"La herramienta «{paso.get('herramienta')}» no está permitida en protocolos."
        if not isinstance(paso.get("argumentos", {}), dict):
            return "Los argumentos de cada paso deben ser un objeto."
    return None


def ejecutar(nombre: str) -> str:
    """Corre los pasos en orden. Devuelve lo que diría Jarvis y, abajo, lo que no salió bien."""
    from tools.registry import call_tool

    encontrado = buscar(nombre)
    if encontrado is None:
        return f"No conozco el protocolo «{nombre}». " + listar()
    nombre_p, protocolo = encontrado
    frase, detalles, fallos = "", [], []
    for paso in protocolo.get("pasos", []):
        if "decir" in paso:
            frase = paso["decir"]
            continue
        herramienta = paso.get("herramienta")
        if herramienta not in PERMITIDAS:
            fallos.append(f"«{herramienta}» no está permitido")
            continue
        resultado = call_tool(herramienta, json.dumps(paso.get("argumentos", {}), ensure_ascii=False))
        if resultado.startswith(("Error", "No se pudo", "La herramienta", "⛔", "Herramienta desconocida", "No encuentro")):
            fallos.append(f"{herramienta}: {resultado[:120]}")
        elif herramienta in {"listar_tareas", "informe_seguridad_red", "estado_hardware", "listar_procesos_pesados",
                             "leer_noticias_rss"}:
            detalles.append(resultado)
    respuesta = frase or f"Protocolo {nombre_p} completado."
    if fallos:
        respuesta += " Ojo: " + "; ".join(fallos) + "."
    if detalles:
        respuesta += "\n\n" + "\n\n".join(detalles)
    return respuesta


_PLANIFICAR = """Convierte la descripción en un protocolo para un asistente de Windows.
Responde SOLO un JSON: {{"descripcion": "una frase", "pasos": [ ... ]}}.
Cada paso es {{"herramienta": "nombre", "argumentos": {{...}}}} o {{"decir": "frase final corta en español"}}.
Herramientas permitidas (no uses otras):
{herramientas}
Termina con un paso "decir" al estilo J.A.R.V.I.S. (sereno, breve).
Nombre del protocolo: {nombre}
Descripción del usuario: {descripcion}"""


def crear(nombre: str, descripcion: str) -> str:
    """Pide al modelo los pasos, los valida, te los muestra y solo los guarda si los apruebas."""
    from core.router import ModelRouter
    from core.self_coder import confirmar, confirmation_allowed

    nombre = (nombre or "").strip().lower()
    if not nombre or not (descripcion or "").strip():
        return "Dime el nombre del protocolo y qué debe hacer."
    if not confirmation_allowed():
        return "Los protocolos nuevos se aprueban en la consola del PC."
    herramientas = "\n".join(f"- {n}: {d}" for n, d in PERMITIDAS.items())
    try:
        respuesta, _motor = ModelRouter().complete(descripcion, prefer_cloud=True, messages=[
            {"role": "user", "content": _PLANIFICAR.format(herramientas=herramientas, nombre=nombre, descripcion=descripcion)}])
        texto = respuesta.choices[0].message.content or ""
        plan = json.loads(texto[texto.index("{"): texto.rindex("}") + 1])
    except Exception as exc:
        return f"No pude planificar el protocolo: {type(exc).__name__}."
    motivo = validar(plan.get("pasos"))
    if motivo:
        return f"El plan propuesto no es seguro o no es válido: {motivo}"
    resumen = "\n".join(f"  {i}. " + (f"decir: {p['decir']}" if "decir" in p else
                                        f"{p['herramienta']} {json.dumps(p.get('argumentos', {}), ensure_ascii=False)}")
                        for i, p in enumerate(plan["pasos"], 1))
    if not confirmar(f"¿Guardar el protocolo «{nombre}»?\n{resumen}"):
        return "No lo guardé."
    propios = _propios()
    propios[nombre] = {"descripcion": str(plan.get("descripcion", descripcion))[:200], "pasos": plan["pasos"]}
    ARCHIVO.parent.mkdir(parents=True, exist_ok=True)
    ARCHIVO.write_text(json.dumps(propios, ensure_ascii=False, indent=2), encoding="utf-8")
    return f"Protocolo «{nombre}» guardado. Actívalo con «activa protocolo {nombre}»."
