"""Revisión de los cambios de código del agente, común a la consola y la app web.

Las comprobaciones viven aquí (y no en cada interfaz) para que ningún canal pueda
aplicar un cambio que no esté esperando revisión o cuyas pruebas fallen sin decirlo.
"""
from __future__ import annotations

import json

from core import programador, tareas


class CambioInvalido(ValueError):
    """El cambio no existe o no está en el estado necesario para esa acción."""


def obtener(id_tarea: str) -> dict:
    tarea = tareas.obtener(id_tarea.strip("[] "))
    if not tarea or tarea["tipo"] != "programa":
        raise CambioInvalido("No hay un cambio de código con ese id.")
    return tarea


def listar(incluir_terminados: bool = False) -> list[dict]:
    return [t for t in tareas.listar(incluir_terminadas=incluir_terminados, limite=100) if t["tipo"] == "programa"]


def revisar(id_tarea: str) -> dict:
    tarea = obtener(id_tarea)
    extra = tareas.datos(tarea)
    texto = programador.diff(tarea["id"]) if extra.get("commit") and not extra.get("merge") else ""
    return {"tarea": tarea, "datos": extra, "diff": texto, "avisos": programador.avisos_de_seguridad(texto),
            "puede_empezar": tarea["estado"] == "esperando_autorizacion" and not extra,
            "puede_aplicar": tarea["estado"] == "esperando_autorizacion" and bool(extra.get("commit")),
            "puede_deshacer": bool(extra.get("merge")) and not extra.get("revert")}


def autorizar_inicio(id_tarea: str) -> str:
    if not tareas.autorizar_inicio(obtener(id_tarea)["id"]):
        raise CambioInvalido("Ese cambio no está esperando aprobación para empezar.")
    return "Cambio aprobado: el agente empieza en segundo plano y te aviso al terminar."


def aplicar(id_tarea: str, aceptar_pruebas_fallidas: bool = False) -> str:
    """Hace el merge del cambio revisado. Devuelve el commit del merge."""
    tarea = obtener(id_tarea)
    extra = tareas.datos(tarea)
    if tarea["estado"] != "esperando_autorizacion" or not extra.get("commit"):
        raise CambioInvalido("Ese cambio no está esperando revisión.")
    if not extra.get("pruebas_ok") and not aceptar_pruebas_fallidas:
        raise CambioInvalido("Las pruebas FALLAN con este cambio: confirma explícitamente que quieres aplicarlo igual.")
    merge = programador.aprobar(tarea["id"])
    tareas._actualizar(tarea["id"], "aplicado por el usuario", estado="completada", proximo_paso=None,
                       datos=json.dumps({**extra, "merge": merge}))
    return merge


def rechazar(id_tarea: str) -> None:
    tarea = obtener(id_tarea)
    if tarea["estado"] not in tareas.ACTIVAS and tarea["estado"] != "fallida":
        raise CambioInvalido("Ese cambio ya está cerrado.")
    programador.rechazar(tarea["id"])
    tareas._actualizar(tarea["id"], "rechazado por el usuario", estado="cancelada", proximo_paso=None)


def deshacer(id_tarea: str) -> str:
    tarea = obtener(id_tarea)
    extra = tareas.datos(tarea)
    if not extra.get("merge"):
        raise CambioInvalido("Ese cambio no se ha aplicado, no hay nada que deshacer.")
    if extra.get("revert"):
        raise CambioInvalido("Ese cambio ya se deshizo.")
    revert = programador.deshacer(extra["merge"])
    tareas._actualizar(tarea["id"], "deshecho por el usuario", datos=json.dumps({**extra, "revert": revert}))
    return revert
