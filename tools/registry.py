"""Registro OpenAI-compatible de herramientas y despacho controlado."""
from __future__ import annotations

import json
import inspect
import importlib.util
import multiprocessing
import os
import re
import time

from tools import dev_sec_tools, memory_tools, system_tools, vision_tools, web_tools, knowledge_vault, clipboard_tasks, browser_tools


def _tool(name: str, description: str, properties: dict | None = None, required: list[str] | None = None) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties or {}, "required": required or []},
    }}


TOOL_SCHEMAS = [
    _tool("estado_hardware", "Devuelve el uso actual de CPU, RAM, disco y GPU."),
    _tool("listar_procesos_pesados", "Muestra procesos que más memoria RAM consumen."),
    _tool("explorar_directorio", "Lista archivos y carpetas de una ruta local.", {"ruta": {"type": "string"}}),
    _tool("auditar_puertos_locales", "Lista puertos locales TCP/UDP en escucha y su proceso."),
    _tool("leer_codigo_fuente", "Lee un archivo con números de línea.", {
        "ruta_archivo": {"type": "string"}, "linea_inicio": {"type": "integer"}, "linea_fin": {"type": "integer"}
    }, ["ruta_archivo"]),
    _tool("estado_git", "Muestra status y últimos commits de un repositorio.", {"ruta_repositorio": {"type": "string"}}),
    _tool("ejecutar_powershell_seguro", "Ejecuta PowerShell; pide confirmación salvo comandos de lectura permitidos y bloquea destructivos.", {"comando": {"type": "string"}}, ["comando"]),
    _tool("guardar_recuerdo_importante", "Guarda un dato personal o preferencia en memoria semántica.", {"dato": {"type": "string"}, "categoria": {"type": "string"}}, ["dato", "categoria"]),
    _tool("buscar_en_memoria_profunda", "Busca recuerdos personales relevantes.", {"consulta": {"type": "string"}}, ["consulta"]),
    _tool("indexar_proyecto_local", "Indexa archivos locales compatibles para RAG.", {"ruta_carpeta": {"type": "string"}}, ["ruta_carpeta"]),
    _tool("autoprogramar_habilidad", "Aprende una habilidad nueva de cálculo o de texto (fechas, conversiones, conteos, extracción con regex, formatos). No sirve para archivos, registro, comandos, internet ni abrir programas.", {"objetivo": {"type": "string"}, "nombre_funcion": {"type": "string"}}, ["objetivo", "nombre_funcion"]),
    _tool("ver_pantalla_actual", "Captura la pantalla y extrae texto mediante OCR local.", {"pregunta": {"type": "string"}}),
    _tool("buscar_en_internet", "Investiga documentación y resultados web actuales.", {"consulta": {"type": "string"}, "max_resultados": {"type": "integer"}}, ["consulta"]),
    _tool("investigar_tema", "Investiga un tema en internet (busca, lee varias páginas) y devuelve un resumen con fuentes. Úsala para 'investiga', 'averigua', 'resúmeme' o noticias.", {"tema": {"type": "string"}}, ["tema"]),
    _tool("leer_documentacion_web", "Lee y limpia una página de documentación.", {"url": {"type": "string"}}, ["url"]),
    _tool("crear_o_actualizar_nota", "Guarda una nota Markdown en la bóveda.", {"titulo": {"type": "string"}, "contenido": {"type": "string"}, "carpeta": {"type": "string"}, "tags": {"type": "string"}}, ["titulo", "contenido"]),
    _tool("buscar_en_boveda", "Busca notas Markdown locales.", {"consulta": {"type": "string"}}, ["consulta"]),
    _tool("registrar_en_bitacora_diaria", "Añade una entrada al diario Markdown.", {"nota": {"type": "string"}}, ["nota"]),
    _tool("leer_portapapeles", "Lee el texto actual del portapapeles de Windows."),
    _tool("copiar_al_portapapeles", "Copia texto al portapapeles de Windows.", {"texto": {"type": "string"}}, ["texto"]),
    _tool("programar_recordatorio", "Programa un recordatorio que sobrevive a reinicios y avisa también por Telegram. Usa minutos desde ahora u hora HH:MM.", {"mensaje": {"type": "string"}, "minutos": {"type": "integer"}, "hora": {"type": "string"}}, ["mensaje"]),
    _tool("crear_tarea", "Encarga un trabajo para hacerlo en segundo plano (investigar, revisar, preparar algo) y avisar al terminar. Opcional: hora HH:MM para empezar.", {"objetivo": {"type": "string"}, "hora": {"type": "string"}}, ["objetivo"]),
    _tool("listar_tareas", "Muestra las tareas y recordatorios pendientes o en curso."),
    _tool("cancelar_tarea", "Cancela una tarea o recordatorio por su id.", {"id": {"type": "string"}}, ["id"]),
    _tool("automatizar_navegador", "Lee páginas o ejecuta acciones declarativas con Playwright.", {"url": {"type": "string"}, "acciones": {"type": "string"}}, ["url"]),
    _tool("listar_aplicaciones", "Lista las aplicaciones instaladas en el PC (menú Inicio y Microsoft Store); filtro opcional por nombre.", {"filtro": {"type": "string"}}),
    _tool("listar_habilidades_disponibles", "Enumera las capacidades actuales, incluidas las aprendidas por Tool Forge."),
]
_BUILTIN_TOOL_NAMES = {schema["function"]["name"] for schema in TOOL_SCHEMAS}

FUNCTIONS = {
    "estado_hardware": lambda a: system_tools.estado_hardware(),
    "listar_procesos_pesados": lambda a: system_tools.listar_procesos_pesados(),
    "explorar_directorio": lambda a: system_tools.explorar_directorio(a.get("ruta", ".")),
    "auditar_puertos_locales": lambda a: dev_sec_tools.auditar_puertos_locales(),
    "leer_codigo_fuente": lambda a: dev_sec_tools.leer_codigo_fuente(a["ruta_archivo"], a.get("linea_inicio", 1), a.get("linea_fin", 120)),
    "estado_git": lambda a: dev_sec_tools.estado_git(a.get("ruta_repositorio", ".")),
    "ejecutar_powershell_seguro": lambda a: dev_sec_tools.ejecutar_powershell_seguro(a["comando"]),
    "autoprogramar_habilidad": lambda a: _autoprogramar_dispatch(a),
    "ver_pantalla_actual": lambda a: vision_tools.ver_pantalla_actual(a.get("pregunta", "")),
    "buscar_en_internet": lambda a: web_tools.buscar_en_internet(a["consulta"], a.get("max_resultados", 5)),
    "investigar_tema": lambda a: web_tools.investigar_tema(a.get("tema") or a.get("consulta", "")),
    "leer_documentacion_web": lambda a: web_tools.leer_documentacion_web(a["url"]),
    "crear_o_actualizar_nota": lambda a: knowledge_vault.crear_o_actualizar_nota(a["titulo"], a["contenido"], a.get("carpeta", "Proyectos"), a.get("tags", "")),
    "buscar_en_boveda": lambda a: knowledge_vault.buscar_en_boveda(a["consulta"]),
    "registrar_en_bitacora_diaria": lambda a: knowledge_vault.registrar_en_bitacora_diaria(a["nota"]),
    "leer_portapapeles": lambda a: clipboard_tasks.leer_portapapeles(),
    "copiar_al_portapapeles": lambda a: clipboard_tasks.copiar_al_portapapeles(a["texto"]),
    "programar_recordatorio": lambda a: clipboard_tasks.programar_recordatorio(a["mensaje"], a.get("minutos", 0), a.get("hora", "")),
    "crear_tarea": lambda a: _crear_tarea(a.get("objetivo", ""), a.get("hora", "")),
    "listar_tareas": lambda a: _listar_tareas(),
    "cancelar_tarea": lambda a: _cancelar_tarea(str(a.get("id", ""))),
    "automatizar_navegador": lambda a: browser_tools.automatizar_navegador(a["url"], a.get("acciones", "[]")),
    "listar_aplicaciones": lambda a: system_tools.listar_aplicaciones(a.get("filtro", "")),
    "listar_habilidades_disponibles": lambda a: listar_habilidades_disponibles(),
    "guardar_recuerdo_importante": lambda a: memory_tools.guardar_recuerdo_importante(a["dato"], a["categoria"]),
    "buscar_en_memoria_profunda": lambda a: memory_tools.buscar_en_memoria_profunda(a["consulta"]),
    "indexar_proyecto_local": lambda a: memory_tools.indexar_proyecto_local(a["ruta_carpeta"]),
}


def _crear_tarea(objetivo: str, hora: str = "") -> str:
    from datetime import datetime, timedelta
    from core import tareas
    if not objetivo.strip():
        return "Falta el objetivo de la tarea."
    cuando = None
    if hora:
        try:
            hh, mm = (int(p) for p in hora.split(":")[:2])
            cuando = datetime.now().replace(hour=hh, minute=mm, second=0, microsecond=0)
            cuando += timedelta(days=1) if cuando <= datetime.now() else timedelta()
        except ValueError:
            return f"Hora no válida: {hora}. Usa HH:MM."
    id_tarea = tareas.crear("agente", objetivo, cuando=cuando)
    return f"Tarea [{id_tarea}] creada. La haré en segundo plano y te aviso al terminar (también por Telegram)."


def _listar_tareas() -> str:
    from core import tareas
    activas = tareas.listar()
    return "\n".join(tareas.describir(t) for t in activas) or "No hay tareas ni recordatorios pendientes."


def _cancelar_tarea(id_tarea: str) -> str:
    from core import tareas
    return f"Tarea {id_tarea} cancelada." if tareas.cancelar(id_tarea.strip("[] ")) else f"No hay una tarea activa con id {id_tarea}."


def listar_habilidades_disponibles() -> str:
    """Devuelve el inventario actual sin exponer código interno ni secretos."""
    custom = []
    try:
        from core.self_coder import listar_habilidades
        custom = [item.get("name", "") for item in listar_habilidades()]
    except Exception:
        pass
    built_in = sorted(name for name in FUNCTIONS if name not in custom)
    return "Habilidades integradas:\n- " + "\n- ".join(built_in) + "\n\nHabilidades aprendidas:\n- " + ("\n- ".join(custom) or "(ninguna)")


def _autoprogramar_dispatch(arguments: dict) -> str:
    """Normaliza aliases de modelos locales antes de llamar al Tool Forge."""
    from core.self_coder import autoprogramar_habilidad
    return autoprogramar_habilidad(
        objetivo=arguments.get("objetivo") or arguments.get("descripcion", ""),
        nombre_funcion=arguments.get("nombre_funcion") or arguments.get("nombre_habilidad") or arguments.get("name"),
        codigo_python=arguments.get("codigo_python") or arguments.get("funcion") or arguments.get("code"),
        descripcion=arguments.get("descripcion"),
    )


def obtener_herramientas_relevantes(prompt: str, es_local: bool) -> list | None:
    """Reduce el contexto local a un pequeño conjunto de herramientas pertinentes."""
    if not es_local:
        return TOOL_SCHEMAS
    text = prompt.lower()
    philosophical = any(word in text for word in ("pensamiento propio", "pensamientos propios", "conciencia", "consciencia", "sentimientos propios"))
    groups = {
        "hardware": {"estado_hardware", "listar_procesos_pesados", "auditar_puertos_locales"},
        "archivo": {"explorar_directorio", "leer_codigo_fuente", "estado_git", "indexar_proyecto_local"},
        "pantalla": {"ver_pantalla_actual"},
        "web": {"investigar_tema", "buscar_en_internet", "leer_documentacion_web"},
        "memoria": {"guardar_recuerdo_importante", "buscar_en_memoria_profunda", "buscar_en_boveda"},
        "nota": {"crear_o_actualizar_nota", "registrar_en_bitacora_diaria", "buscar_en_boveda"},
        "program": {"autoprogramar_habilidad"},
        "portapapeles": {"leer_portapapeles", "copiar_al_portapapeles"},
        "recordatorio": {"programar_recordatorio", "listar_tareas", "cancelar_tarea"},
        "tarea": {"crear_tarea", "listar_tareas", "cancelar_tarea"},
        "navegador": {"automatizar_navegador"},
        "habilidad": {"listar_habilidades_disponibles", "autoprogramar_habilidad"},
        "aplicacion": {"abrir_aplicacion", "listar_aplicaciones"},
    }
    selected: set[str] = set()
    priority: list[str] = []
    keywords = {
        "hardware": ("hardware", "consumo", "pc", "cpu", "ram", "gpu", "vram", "proceso", "puerto", "red"),
        "archivo": ("archivo", "carpeta", "código", "codigo", "git", "proyecto", "pdf", "csv"),
        "pantalla": ("pantalla", "monitor", "ver", "captura", "ocr"),
        "web": ("internet", "web", "documentación", "documentacion", "url", "api", "investiga", "investigar",
                "averigua", "resumen", "resume", "resúmeme", "resumeme", "noticia", "noticias"),
        "memoria": ("recuerdo", "memoria", "preferencia", "aprendiste"),
        "nota": ("nota", "bóveda", "boveda", "diario", "obsidian"),
        "program": ("no sabes", "forja", "autoprograma", "programa una herramienta", "habilidad"),
        "portapapeles": ("portapapeles", "copié", "copie", "copiado", "pegar"),
        "recordatorio": ("recordatorio", "avísame", "avisame", "minutos"),
        "tarea": ("tarea", "segundo plano", "encárgate", "encargate", "cuando termines", "pendiente"),
        "navegador": ("navegador", "browser", "formulario", "página", "pagina", "playwright"),
        "habilidad": ("habilidad", "capacidad", "puedes hacer", "sabes hacer", "no sabes", "aprende"),
        "aplicacion": ("abre", "abrir", "aplicación", "aplicacion", "app", "programa", "instalado", "instalada"),
    }
    for group, words in keywords.items():
        # Acepta el plural: "procesos", "habilidades", "puertos".
        if any(
            (word in text if " " in word else re.search(rf"(?<!\w){re.escape(word)}(?:s|es)?(?!\w)", text))
            for word in words
        ):
            selected.update(groups[group])
            priority.extend(groups[group])
    if philosophical:
        selected.discard("autoprogramar_habilidad")
        priority = [name for name in priority if name != "autoprogramar_habilidad"]
    if any(word in text for word in ("excel", "xlsx", "scraping", "scraper", "indicador", "convierte", "convertir")):
        selected.add("autoprogramar_habilidad")
        priority.insert(0, "autoprogramar_habilidad")
    related_custom = _habilidades_relacionadas(text)
    if not selected and not related_custom:
        # Una petición operativa no cubierta debe poder activar el Tool Forge.
        action_words = ("haz", "hacer", "crea", "convierte", "calcula", "cuenta", "cuantos", "cuántos",
                        "automatiza", "descarga", "exporta", "procesa", "analiza", "genera", "extrae")
        if any(re.search(rf"(?<!\w){re.escape(word)}", text) for word in action_words):
            selected = {"autoprogramar_habilidad"}
            priority = ["autoprogramar_habilidad"]
        else:
            return None
    # Conserva primero las herramientas del grupo que activó la consulta,
    # evitando que un grupo grande oculte, por ejemplo, el portapapeles.
    ordered_names = list(dict.fromkeys(priority))
    if "portapapeles" in text or "copié" in text or "copie" in text:
        ordered_names.sort(key=lambda name: 0 if "portapapeles" in name else 1)
    selected_list = [schema for name in ordered_names if name in selected for schema in TOOL_SCHEMAS if schema["function"]["name"] == name]
    # Las habilidades aprendidas que encajan con la petición van primero: son
    # más específicas que las integradas.
    visible = related_custom[:3]
    visible_names = {schema["function"]["name"] for schema in visible}
    visible.extend(schema for schema in selected_list if schema["function"]["name"] not in visible_names)
    return visible[:5]


def _sin_acentos(value: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()


_STOPWORDS = {"para", "como", "desde", "hasta", "sobre", "entre", "texto", "habilidad", "generada", "devuelve",
              "funcion", "archivo", "dado", "datos", "valor", "este", "esta", "cual", "cuales"}


def _habilidades_relacionadas(text: str) -> list[dict]:
    """Habilidades aprendidas cuyo nombre o descripción comparte raíces con la petición."""
    words = {word[:5] for word in re.findall(r"[a-z]{4,}", _sin_acentos(text)) if word not in _STOPWORDS}
    if not words:
        return []
    related = []
    for schema in TOOL_SCHEMAS:
        function = schema["function"]
        if function["name"] in _BUILTIN_TOOL_NAMES:
            continue
        vocabulary = _sin_acentos(function["name"].replace("_", " ") + " " + function.get("description", ""))
        roots = {word[:5] for word in re.findall(r"[a-z]{4,}", vocabulary) if word not in _STOPWORDS}
        if words & roots:
            related.append(schema)
    return related


def register_custom_tool(name: str, description: str, function: object) -> None:
    """Registra una función custom con wrapper de argumentos JSON y esquema flexible."""
    if name in FUNCTIONS:
        return
    adapter = lambda args, fn=function: _invoke_flexible(fn, args)
    adapter._tool_target = function
    FUNCTIONS[name] = adapter
    properties = {}
    required = []
    try:
        for parameter_name, parameter in inspect.signature(function).parameters.items():
            if parameter_name == "self":
                continue
            annotation = parameter.annotation
            json_type = "integer" if annotation is int else "number" if annotation is float else "boolean" if annotation is bool else "string"
            properties[parameter_name] = {"type": json_type}
            if parameter.default is inspect.Parameter.empty:
                required.append(parameter_name)
    except (TypeError, ValueError):
        properties = {"kwargs": {"type": "object"}}
    TOOL_SCHEMAS.append(_tool(name, description, properties, required))


def _invoke_flexible(function, arguments: dict) -> object:
    """Invoca funciones custom tolerando aliases y argumentos extra del LLM."""
    signature = inspect.signature(function)
    parameters = list(signature.parameters.values())
    named = {p.name: p for p in parameters if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)}
    accepts_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters)
    arguments = arguments if isinstance(arguments, dict) else {}
    mapped = {key: value for key, value in arguments.items() if key in named}
    for key, value in arguments.items():
        if key in named:
            continue
        available = [name for name in named if name not in mapped]
        normalized = key.lower().replace("-", "_")
        path_params = [name for name in available if any(token in name.lower() for token in ("ruta", "path", "archivo", "file"))]
        target = path_params[0] if path_params and any(token in normalized for token in ("ruta", "path", "archivo", "file")) else (available[0] if available else None)
        if target:
            mapped[target] = value
    if accepts_kwargs:
        for key, value in arguments.items():
            mapped.setdefault(key, value)
    return function(**mapped)


def _custom_worker(module_path: str, function_name: str, arguments: dict, output) -> None:
    """Ejecuta una habilidad custom en un proceso que puede terminarse."""
    try:
        allowed_environment = {
            "PATH", "SYSTEMROOT", "PROGRAMFILES", "PROGRAMFILES(X86)", "APPDATA",
            "LOCALAPPDATA", "PROGRAMDATA", "TEMP", "TMP", "USERPROFILE",
        }
        preserved = {
            key: value for key, value in os.environ.items()
            if key.upper() in allowed_environment
        }
        os.environ.clear()
        os.environ.update(preserved)
        module_name = f"custom_worker_{function_name}"
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        if spec is None or spec.loader is None:
            raise ImportError("No se pudo cargar la habilidad en el proceso aislado.")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result = getattr(module, function_name)(**arguments)
        output.put((True, str(result)))
    except BaseException as exc:
        output.put((False, f"{type(exc).__name__}: {exc}"))


def _invoke_custom_with_timeout(function, arguments: dict, timeout: float = 15) -> object:
    """Aísla habilidades generadas y corta bucles o bloqueos prolongados."""
    module_path = getattr(function, "_custom_path", None)
    if not module_path:
        module = inspect.getmodule(function)
        module_path = getattr(module, "__file__", None) if module is not None else None
    if not module_path:
        raise RuntimeError("Habilidad custom sin ruta aislable; ejecución principal bloqueada.")
    context = multiprocessing.get_context("spawn")
    output = context.Queue()
    process = context.Process(target=_custom_worker, args=(module_path, function.__name__, arguments, output))
    process.start()
    process.join(timeout)
    if process.is_alive():
        process.terminate()
        process.join(2)
        return "Habilidad cancelada: superó el límite de 15 segundos."
    if not output.empty():
        ok, result = output.get()
        return result if ok else f"Error en habilidad aislada: {result}"
    return f"Habilidad terminó sin resultado (código {process.exitcode})."


def unregister_custom_tool(name: str) -> None:
    FUNCTIONS.pop(name, None)
    TOOL_SCHEMAS[:] = [schema for schema in TOOL_SCHEMAS if schema["function"]["name"] != name]


def call_tool(name: str, raw_arguments: str) -> str:
    """Punto único por el que pasan todas las herramientas: aquí se audita y se respeta la parada."""
    from core import auditoria

    if name not in FUNCTIONS:
        auditoria.registrar("herramienta", name, raw_arguments, "desconocida", ok=False)
        return f"Herramienta desconocida: {name}"
    if auditoria.detenido():
        auditoria.registrar("herramienta", name, raw_arguments, "bloqueada por la parada de emergencia", ok=False)
        return "⛔ Acción no ejecutada: la parada de emergencia está activa (/reanudar para continuar)."
    inicio = time.perf_counter()
    try:
        args = json.loads(raw_arguments or "{}")
        if not isinstance(args, dict):
            return "Argumentos inválidos: se esperaba un objeto JSON."
        args = _unwrap_schema_values(args)
        tool = FUNCTIONS[name]
        target = getattr(tool, "_tool_target", None)
        result = str(_invoke_custom_with_timeout(target, _invoke_arguments(target, args)) if target is not None else tool(args))
        auditoria.registrar("herramienta", name, args, result, ok=not result.startswith(("Error", "No se pudo")),
                            segundos=round(time.perf_counter() - inicio, 2))
        return result
    except Exception as exc:
        auditoria.registrar("herramienta", name, raw_arguments, f"{type(exc).__name__}: {exc}", ok=False,
                            segundos=round(time.perf_counter() - inicio, 2))
        try:
            from memory.learning_loop import registrar_fallo
            return registrar_fallo(name, exc)
        except Exception:
            pass
        return f"Error en {name}: {type(exc).__name__}: {exc}"


def _unwrap_schema_values(arguments: dict) -> dict:
    """Acepta el formato erróneo que algunos modelos usan para argumentos."""
    return {
        key: value.get("value") if isinstance(value, dict) and "value" in value else value
        for key, value in arguments.items()
    }


def _invoke_arguments(function, arguments: dict) -> dict:
    """Convierte aliases del modelo en argumentos antes del proceso aislado."""
    signature = inspect.signature(function)
    parameters = list(signature.parameters.values())
    named = {p.name: p for p in parameters if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)}
    accepts_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters)
    mapped = {key: value for key, value in arguments.items() if key in named}
    for key, value in arguments.items():
        if key in named:
            continue
        available = [name for name in named if name not in mapped]
        normalized = key.lower().replace("-", "_")
        path_params = [name for name in available if any(token in name.lower() for token in ("ruta", "path", "archivo", "file"))]
        target = path_params[0] if path_params and any(token in normalized for token in ("ruta", "path", "archivo", "file")) else (available[0] if available else None)
        if target:
            mapped[target] = value
    if accepts_kwargs:
        for key, value in arguments.items():
            mapped.setdefault(key, value)
    return mapped
