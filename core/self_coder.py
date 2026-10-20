"""Forja de herramientas Python con validación estática, pruebas aisladas y registro en caliente.

El código generado nunca se ejecuta antes de pasar las comprobaciones AST. Tras
validarlo, sus pruebas corren en el worker aislado (sin entorno ni archivos) y
solo se guarda e instala con confirmación explícita del usuario.
"""
from __future__ import annotations

import ast
import contextlib
import contextvars
import hashlib
import inspect
import json
import re
import subprocess
from pathlib import Path

from rich.prompt import Confirm
from rich.syntax import Syntax
from rich.console import Console

from config import settings

CUSTOM_DIR = settings.ROOT_DIR / "tools" / "custom_skills"
MANIFEST_PATH = CUSTOM_DIR / "manifest.json"
_loaded_modules: dict[str, object] = {}
_confirmation_allowed = contextvars.ContextVar("confirmation_allowed", default=True)

_FORBIDDEN_TEXT = (
    "shutil.rmtree", "os.remove", "os.unlink", "Path.unlink", "Path.rmdir",
    "format-volume", "stop-computer", "remove-item", "subprocess.Popen",
    "subprocess.call", "subprocess.run", "os.system", "eval(", "exec(",
)
_ALLOWED_IMPORTS = {"hashlib", "json", "pathlib", "csv", "re", "datetime", "__future__"}
_ALLOWED_MODULE_ATTRIBUTES = {
    "hashlib": {"sha256", "sha1", "md5", "new", "algorithms_available"},
    "json": {"dumps", "loads", "JSONDecodeError"},
    "pathlib": {"Path", "PurePath", "PurePosixPath", "PureWindowsPath"},
    "csv": {"reader", "writer", "DictReader", "DictWriter"},
    "re": {"compile", "search", "match", "fullmatch", "sub", "split", "findall", "escape"},
    "datetime": {"datetime", "date", "timedelta", "timezone"},
    "__future__": {"annotations"},
}
_FORBIDDEN_NAMES = {
    "__import__", "eval", "exec", "compile", "open", "breakpoint", "globals", "vars",
    "locals", "getattr", "setattr", "delattr", "type", "input",
}
_FORBIDDEN_ATTRIBUTES = {
    "unlink", "rmdir", "write_text", "write_bytes", "rename", "replace", "startfile",
    "popen", "system", "run", "call", "Popen", "open", "chmod", "touch", "mkdir",
    "symlink_to", "hardlink_to", "link_to", "read_text", "read_bytes",
}


_ui_pause = contextvars.ContextVar("ui_pause", default=None)
# Nombre de la última habilidad instalada, para que el cerebro la ofrezca en el mismo turno.
ULTIMA_HABILIDAD: str | None = None


def set_ui_pause(factory):
    """Registra un context manager que pausa la UI en vivo mientras se pregunta al usuario."""
    return _ui_pause.set(factory)


def reset_ui_pause(token) -> None:
    _ui_pause.reset(token)


def confirmar(pregunta: str, mostrar=None) -> bool:
    """Pregunta sí/no sin que la animación de la consola tape el texto."""
    factory = _ui_pause.get()
    from core import auditoria

    with factory() if factory else contextlib.nullcontext():
        if mostrar:
            mostrar()
        aprobada = Confirm.ask(pregunta, default=False)
    auditoria.registrar("confirmacion", pregunta, resultado="aprobada" if aprobada else "rechazada", ok=aprobada)
    return aprobada


def confirmation_allowed() -> bool:
    return _confirmation_allowed.get()


def confirmation_context(allowed: bool):
    return _confirmation_allowed.set(allowed)


def reset_confirmation_context(token) -> None:
    _confirmation_allowed.reset(token)


def _manifest() -> list[dict]:
    CUSTOM_DIR.mkdir(parents=True, exist_ok=True)
    if not MANIFEST_PATH.exists():
        MANIFEST_PATH.write_text("[]", encoding="utf-8")
    try:
        value = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _save_manifest(items: list[dict]) -> None:
    MANIFEST_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def _validate(name: str, code: str) -> ast.Module:
    if not re.fullmatch(r"[A-Za-z_]\w*", name):
        raise ValueError("El nombre de función no es un identificador Python válido.")
    tree = ast.parse(code, filename=f"{name}.py", mode="exec")
    definitions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name]
    if not definitions:
        raise ValueError(f"El código debe definir def {name}(...).")
    allowed_top_level = (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef)
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            continue
        if not isinstance(node, allowed_top_level):
            raise ValueError("El nivel superior solo puede contener imports, docstring y funciones.")
    for function in (node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))):
        if function.decorator_list:
            raise ValueError("Los decoradores están bloqueados en habilidades generadas.")
    module_aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.startswith("__"):
            raise ValueError("Las cadenas de protocolo interno están bloqueadas en habilidades generadas.")
        if isinstance(node, ast.Name) and node.id in _FORBIDDEN_NAMES:
            raise ValueError(f"Nombre bloqueado en habilidad generada: {node.id}")
        if isinstance(node, ast.While):
            raise ValueError("Los bucles while están bloqueados en habilidades generadas.")
        if isinstance(node, ast.Import):
            for alias in node.names:
                module = alias.name.split(".")[0]
                if alias.name != module or module not in _ALLOWED_IMPORTS:
                    raise ValueError("Import fuera de la lista blanca en habilidad generada.")
                module_aliases[alias.asname or module] = module
        if isinstance(node, ast.ImportFrom):
            module = (node.module or "").split(".")[0]
            if node.level or module not in _ALLOWED_IMPORTS:
                raise ValueError("Import fuera de la lista blanca en habilidad generada.")
            for alias in node.names:
                if alias.name not in _ALLOWED_MODULE_ATTRIBUTES[module]:
                    raise ValueError(f"Símbolo no permitido desde {module}: {alias.name}")
        if isinstance(node, ast.Attribute) and (
            node.attr.startswith("_") or node.attr in _FORBIDDEN_ATTRIBUTES
        ):
            raise ValueError(f"Atributo bloqueado en habilidad generada: {node.attr}")
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            module = module_aliases.get(node.value.id)
            if module and node.attr not in _ALLOWED_MODULE_ATTRIBUTES[module]:
                raise ValueError(f"Atributo no permitido desde {module}: {node.attr}")
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in _FORBIDDEN_NAMES:
                raise ValueError(f"Llamada bloqueada en habilidad generada: {node.func.id}")
            text = ast.unparse(node).lower()
            if any(token.lower() in text for token in _FORBIDDEN_TEXT):
                raise ValueError(f"Llamada potencialmente destructiva bloqueada: {text[:100]}")
            if isinstance(node.func, ast.Name) and node.func.id == "range" and node.args:
                range_arg = node.args[0]
                if not isinstance(range_arg, ast.Constant) or not isinstance(range_arg.value, int) or range_arg.value > 10000:
                    raise ValueError("range demasiado grande en habilidad generada.")
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defaults = [*node.args.defaults, *(item for item in node.args.kw_defaults if item is not None)]
            if any(isinstance(child, ast.Call) for default in defaults for child in ast.walk(default)):
                raise ValueError("Las llamadas en argumentos por defecto están bloqueadas.")
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            raise ValueError("La habilidad contiene una llamada ejecutable fuera de su función.")
    return tree


def _signature_from_ast(function: ast.FunctionDef | ast.AsyncFunctionDef) -> inspect.Signature:
    """Construye la firma pública sin importar ni ejecutar el módulo."""
    parameters: list[inspect.Parameter] = []
    positional = [*getattr(function.args, "posonlyargs", []), *function.args.args]
    defaults = [inspect.Parameter.empty] * (len(positional) - len(function.args.defaults))
    defaults.extend(_literal_default(value) for value in function.args.defaults)
    for index, argument in enumerate(positional):
        kind = inspect.Parameter.POSITIONAL_ONLY if index < len(getattr(function.args, "posonlyargs", [])) else inspect.Parameter.POSITIONAL_OR_KEYWORD
        parameters.append(inspect.Parameter(argument.arg, kind, default=defaults[index], annotation=_annotation_value(argument.annotation)))
    if function.args.vararg:
        parameters.append(inspect.Parameter(function.args.vararg.arg, inspect.Parameter.VAR_POSITIONAL))
    for argument, default in zip(function.args.kwonlyargs, function.args.kw_defaults):
        parameters.append(inspect.Parameter(argument.arg, inspect.Parameter.KEYWORD_ONLY, default=_literal_default(default), annotation=_annotation_value(argument.annotation)))
    if function.args.kwarg:
        parameters.append(inspect.Parameter(function.args.kwarg.arg, inspect.Parameter.VAR_KEYWORD))
    return inspect.Signature(parameters)


def _literal_default(node: ast.AST | None) -> object:
    if node is None:
        return inspect.Parameter.empty
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError):
        return inspect.Parameter.empty


def _annotation_value(node: ast.AST | None) -> object:
    if isinstance(node, ast.Name) and node.id in {"str", "int", "float", "bool"}:
        return {"str": str, "int": int, "float": float, "bool": bool}[node.id]
    return inspect.Parameter.empty


class _LazySkill:
    """Proxy que permite registrar la firma sin ejecutar código no aislado."""

    def __init__(self, name: str, path: Path, signature: inspect.Signature) -> None:
        self.__name__ = name
        self._custom_path = str(path)
        self.__signature__ = signature

    def __call__(self, **_kwargs):
        raise RuntimeError("La habilidad custom solo puede ejecutarse en el worker aislado.")


def _load(name: str, path: Path) -> object:
    """Registra una habilidad sin importar su módulo en el proceso principal."""
    code = path.read_text(encoding="utf-8")
    tree = ast.parse(code, filename=str(path), mode="exec")
    if not any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name for node in tree.body):
        raise ValueError(f"La habilidad {name} no expone una función invocable.")
    function = next(node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name)
    proxy = _LazySkill(name, path, _signature_from_ast(function))
    _loaded_modules[name] = proxy
    return proxy


def _register(name: str, description: str, function: object) -> None:
    from tools.registry import register_custom_tool
    register_custom_tool(name, description, function)


def crear_y_cargar_herramienta(
    nombre_funcion: str,
    descripcion: str,
    codigo_python: str,
    paquetes_pip: list[str] | None = None,
    informe_pruebas: list[str] | None = None,
) -> str:
    """Valida y carga una habilidad solo tras confirmación interactiva explícita."""
    global ULTIMA_HABILIDAD
    paquetes_pip = paquetes_pip or []
    _validate(nombre_funcion, codigo_python)
    if not confirmation_allowed():
        return "Habilidad rechazada: las confirmaciones solo están disponibles desde la consola local."

    def mostrar() -> None:
        console = Console()
        console.print(Syntax(codigo_python, "python", line_numbers=True, theme="monokai"))
        if informe_pruebas:
            console.print("[bold]Pruebas en el entorno aislado:[/bold]\n" + "\n".join(informe_pruebas))

    if not confirmar(f"¿Autorizas guardar e importar la habilidad generada '{nombre_funcion}'?", mostrar):
        return "Habilidad rechazada: no se guardó ni se ejecutó código generado."
    if paquetes_pip:
        clean_packages = [p for p in paquetes_pip if re.fullmatch(r"[A-Za-z0-9_.-]+(?:==[A-Za-z0-9_.-]+)?", p)]
        if len(clean_packages) != len(paquetes_pip):
            return "Paquetes rechazados: nombre inválido."
        if not confirmar(f"¿Instalar dependencias para {nombre_funcion}: {', '.join(clean_packages)}?"):
            return "Instalación cancelada; no se creó la habilidad."
        pip_path = settings.ROOT_DIR / ".venv" / "Scripts" / "pip.exe"
        result = subprocess.run([str(pip_path), "install", *clean_packages], shell=False, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            return f"Falló pip: {result.stderr[-1500:]}"
    CUSTOM_DIR.mkdir(parents=True, exist_ok=True)
    path = CUSTOM_DIR / f"{nombre_funcion}.py"
    guardado = codigo_python.rstrip() + "\n"
    path.write_text(guardado, encoding="utf-8")
    function = _load(nombre_funcion, path)
    _register(nombre_funcion, descripcion, function)
    items = [item for item in _manifest() if item.get("name") != nombre_funcion]
    items.append({
        "name": nombre_funcion,
        "description": descripcion,
        "file": path.name,
        # La huella es la del archivo tal como queda guardado, o no coincidiría al arrancar.
        "sha256": hashlib.sha256(guardado.encode("utf-8")).hexdigest(),
        "approved": True,
    })
    _save_manifest(items)
    ULTIMA_HABILIDAD = nombre_funcion
    from core import auditoria
    auditoria.registrar("habilidad", nombre_funcion, descripcion, "instalada", sha256=items[-1]["sha256"])
    return f"Habilidad '{nombre_funcion}' validada, cargada y registrada en caliente."


def _corregir_huella(nombre: str, digest: str) -> None:
    items = _manifest()
    for item in items:
        if item.get("name") == nombre:
            item["sha256"] = digest
    _save_manifest(items)


def cargar_habilidades_guardadas() -> list[str]:
    """Carga al arrancar las habilidades aprobadas; las demás piden confirmación."""
    loaded = []
    for path in sorted(CUSTOM_DIR.glob("*.py")) if CUSTOM_DIR.exists() else []:
        if path.name == "__init__.py":
            continue
        name = path.stem
        try:
            code = path.read_text(encoding="utf-8")
            item = next((x for x in _manifest() if x.get("name") == name), {})
            digest = hashlib.sha256(code.encode("utf-8")).hexdigest()
            aprobada = str(item.get("sha256", "")).lower() if item.get("approved") is True else ""
            trusted = aprobada == digest
            if not trusted and aprobada and aprobada == hashlib.sha256(code.rstrip().encode("utf-8")).hexdigest():
                # Habilidades guardadas antes del arreglo: la huella se calculó sin el salto de línea
                # final. El código es idéntico al aprobado; se corrige la huella una sola vez.
                _corregir_huella(name, digest)
                trusted = True
            if trusted:
                # La aprobación persistida incluye la huella del archivo.
                function = _load(name, path)
                _register(name, item.get("description", f"Habilidad aprendida: {name}"), function)
                loaded.append(name)
                continue
            _validate(name, code)
            if not confirmation_allowed():
                continue
            mostrar = lambda code=code: Console().print(Syntax(code, "python", line_numbers=True, theme="monokai"))
            if not confirmar(f"¿Autorizas importar la habilidad guardada '{name}'?", mostrar):
                continue
            function = _load(name, path)
            _register(name, item.get("description", f"Habilidad aprendida: {name}"), function)
            loaded.append(name)
        except Exception:
            continue
    return loaded


def listar_habilidades() -> list[dict]:
    return _manifest()


def _extraer_codigo_forjado(raw: str, nombre_sugerido: str) -> tuple[str, str, str]:
    """Extrae nombre, descripción y código desde JSON o bloque Python del modelo."""
    text = (raw or "").strip()
    fenced = re.search(r"```(?:json|python)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    candidate = fenced.group(1).strip() if fenced else text
    parsed = None
    try:
        value = json.loads(candidate)
        if isinstance(value, dict):
            parsed = value
    except json.JSONDecodeError:
        pass
    if parsed:
        code = parsed.get("codigo_python") or parsed.get("code") or parsed.get("funcion") or ""
        name = parsed.get("nombre_funcion") or parsed.get("nombre_habilidad") or parsed.get("name") or nombre_sugerido
        description = parsed.get("descripcion") or parsed.get("description") or f"Habilidad generada: {name}"
    else:
        # Algunos modelos devuelven explicación alrededor del código aunque
        # se les pida JSON. Conserva desde el primer `def` y elimina fences.
        code_match = re.search(r"(^|\n)\s*(def\s+[A-Za-z_]\w*\s*\([^\n]*\):[\s\S]*)", candidate)
        code = code_match.group(2).strip() if code_match else candidate
        name = nombre_sugerido
        description = f"Habilidad generada: {name}"
    if not isinstance(code, str):
        raise ValueError("El modelo no devolvió código Python válido.")
    # El nombre real de la función prevalece si el modelo ignoró el nombre sugerido.
    try:
        tree = ast.parse(code)
    except SyntaxError:
        # Segundo intento: si el proveedor devolvió un bloque Python con
        # texto posterior, corta en el siguiente bloque de marcado.
        code = code.split("```", 1)[0].strip()
        tree = ast.parse(code)
    definitions = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)]
    if not definitions:
        raise ValueError("La respuesta no contiene una función def completa.")
    if not re.fullmatch(r"[A-Za-z_]\w*", str(name)):
        name = definitions[0]
    if name not in definitions:
        name = definitions[0]
    return name, str(description), code


_FORGE_PROMPT = """Eres el generador de habilidades de un asistente personal en Windows.
Responde SOLO con dos bloques de código, sin texto adicional:

1) Un bloque ```python con el módulo completo.
2) Un bloque ```json con este objeto:
   {{"nombre_funcion": "snake_case en español",
     "descripcion": "una frase en español con las palabras que usaría el usuario para pedirla",
     "pruebas": [{{"argumentos": {{"param": "valor"}}, "contiene": "texto que DEBE aparecer en el resultado"}}]}}
   Incluye de 2 a 4 pruebas.

Reglas obligatorias del código:
- Una sola función pública `def NOMBRE(...) -> str` con parámetros con nombre, tipados (str, int, float o bool)
  y con valor por defecto ('' , 0, 0.0 o False). Sin *args ni **kwargs.
- Solo puedes importar: datetime, json, re, csv, hashlib, pathlib. Los imports van al inicio del archivo.
- Prohibido: leer o escribir archivos, red, os, sys, subprocess, eval, exec, open, getattr, globals, vars,
  bucles while, decoradores, clases, atributos que empiecen por "_" y range() mayor que 10000.
- Fuera de la función solo puede haber imports y el docstring del módulo.
- Python 3.10: dentro de las llaves de una f-string no puede haber barras invertidas.
- Valida la entrada: ante datos inválidos devuelve un mensaje claro en español, nunca lances excepciones.
- Devuelve siempre texto en español. Las pruebas deben poder comprobarse con el texto exacto de "contiene".

- El resultado nunca afirma que algo pasará o se hizo fuera de la función ("sonará", "enviado", "guardado",
  "programada", "activa"): la función solo calcula y devuelve texto.

Si el objetivo NO se puede cumplir con estas reglas (necesita leer archivos o carpetas, el registro de Windows,
comandos o PowerShell, internet, abrir programas, datos del sistema, programar alarmas, recordatorios o
temporizadores, enviar mensajes o guardar datos), no escribas código: responde solo
```json
{{"imposible": "motivo breve en español"}}
```

Nombre sugerido: {nombre}
Objetivo del usuario: {objetivo}"""

_FALLOS_SANDBOX = ("Error en habilidad aislada", "Habilidad cancelada", "Habilidad terminó sin resultado")
# strict=False admite saltos de línea literales dentro de cadenas JSON, algo que
# los modelos pequeños hacen a menudo al incrustar código.
_JSON_TOLERANTE = json.JSONDecoder(strict=False)


def _sin_acentos(value: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode().lower()


def _primer_objeto_json(text: str) -> dict | None:
    for match in re.finditer(r"\{", text):
        try:
            value, _ = _JSON_TOLERANTE.raw_decode(text[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _motivo_imposible(raw: str) -> str | None:
    """El modelo declara que el objetivo necesita acceso al sistema que las habilidades no tienen."""
    text = re.sub(r"<think>.*?</think>", "", raw or "", flags=re.DOTALL)
    if "```python" in text:
        return None
    meta = _primer_objeto_json(text) or {}
    motivo = meta.get("imposible")
    return str(motivo).strip() if motivo else None


def _extraer_propuesta(raw: str, nombre_sugerido: str) -> dict:
    """Extrae nombre, descripción, código y pruebas de la respuesta del modelo."""
    text = re.sub(r"<think>.*?</think>", "", raw or "", flags=re.DOTALL).strip()
    if not text:
        raise ValueError("La respuesta llegó vacía.")
    python_block = re.search(r"```python\s*\n(.*?)```", text, re.DOTALL | re.IGNORECASE)
    json_block = re.search(r"```json\s*\n(.*?)```", text, re.DOTALL | re.IGNORECASE)
    meta = _primer_objeto_json(json_block.group(1) if json_block else text) or {}
    code = python_block.group(1) if python_block else meta.get("codigo_python") or meta.get("code")
    if not isinstance(code, str) or not code.strip():
        name, description, code = _extraer_codigo_forjado(text, nombre_sugerido)
        return {"nombre": name, "descripcion": description, "codigo": code, "pruebas": []}
    code = re.sub(r"^```(?:python)?\s*|\s*```$", "", code.strip())
    definitions = [node.name for node in ast.parse(code).body if isinstance(node, ast.FunctionDef)]
    if not definitions:
        raise ValueError("El código no contiene una función def.")
    name = str(meta.get("nombre_funcion") or nombre_sugerido)
    if name not in definitions:
        name = definitions[0]
    tests = meta.get("pruebas") if isinstance(meta.get("pruebas"), list) else []
    return {"nombre": name, "descripcion": str(meta.get("descripcion") or f"Habilidad {name}"),
            "codigo": code, "pruebas": [t for t in tests if isinstance(t, dict)][:4]}


def _probar_en_aislado(nombre: str, codigo: str, pruebas: list[dict]) -> tuple[bool, list[str]]:
    """Ejecuta las pruebas propuestas en el worker aislado; el código ya pasó `_validate`."""
    from tools import registry

    if not pruebas:
        return False, ["✗ No incluiste pruebas: agrega 2 a 4 en la clave 'pruebas'."]
    folder = settings.DATA_DIR / "forja_tmp"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{nombre}.py"
    path.write_text(codigo.rstrip() + "\n", encoding="utf-8")
    proxy = _load(nombre, path)
    ok, report = True, []
    for test in pruebas:
        arguments = test.get("argumentos") if isinstance(test.get("argumentos"), dict) else {}
        expected = str(test.get("contiene", ""))
        result = str(registry._invoke_custom_with_timeout(proxy, registry._invoke_arguments(proxy, arguments), timeout=10))
        passed = not result.startswith(_FALLOS_SANDBOX) and _sin_acentos(expected) in _sin_acentos(result)
        ok &= passed
        report.append(f"{'✓' if passed else '✗'} {nombre}({json.dumps(arguments, ensure_ascii=False)}) → {result[:160]!r}"
                      + ("" if passed else f"  (esperaba que contuviera {expected!r})"))
    return ok, report


def _motores_de_forja(router) -> list[tuple[object, str, str, dict]]:
    """La nube programa mejor; el modelo local queda como respaldo sin conexión."""
    motores = []
    if settings.cloud_configurado():
        # Programar puede tardar varios minutos con modelos que razonan; nunca reintentar
        # en silencio porque cada intento se factura.
        cloud = router.cloud.with_options(timeout=300.0, max_retries=0)
        motores.extend((cloud, model, "Cloud", {}) for model in settings.FORGE_MODELS)
    if settings.ollama_activo():
        motores.append((router.local, settings.MODEL_LOCAL, "Local",
                        {"extra_body": {**settings.OLLAMA_EXTRA_BODY, "think": False}}))
    return motores


def _nombre_libre(nombre: str) -> str:
    """Evita que una habilidad aprendida choque con una integrada (que no se registraría)."""
    from tools.registry import _BUILTIN_TOOL_NAMES
    nombre = nombre if re.fullmatch(r"[A-Za-z_]\w*", nombre or "") else "habilidad_generada"
    return f"{nombre}_aprendida" if nombre in _BUILTIN_TOOL_NAMES else nombre


_YA_EXISTE_INTEGRADA = re.compile(
    r"\b(?:alarmas?|recordatorios?|recu[eé]rd(?:a|ame|ale)|av[ií]s(?:a|ame|ale)|despi[eé]rta(?:me)?|temporizador(?:es)?"
    r"|cron[oó]metro|programa(?:r)?\s+un\s+aviso)\b", re.IGNORECASE)


def forjar_con_pruebas(objetivo: str, nombre_sugerido: str = "habilidad_generada", intentos: int = 3,
                       max_llamadas: int = 5) -> str:
    """Genera, valida, prueba y repara una habilidad; la instala solo si el usuario la aprueba."""
    from core.router import ModelRouter

    if _YA_EXISTE_INTEGRADA.search(objetivo or ""):
        # Las habilidades no pueden esperar ni avisar a una hora: sería una alarma falsa.
        return ("No hace falta aprender esto: el asistente ya sabe programar avisos. Herramientas integradas que "
                "sí sirven: programar_recordatorio, listar_tareas, cancelar_tarea. Úsalas ahora.")
    router = ModelRouter()
    nombre_sugerido = _nombre_libre(nombre_sugerido)
    errores = []
    llamadas = 0
    for client, model, origin, extra in _motores_de_forja(router):
        messages = [{"role": "user", "content": _FORGE_PROMPT.format(nombre=nombre_sugerido, objetivo=objetivo)}]
        for intento in range(1, intentos + 1):
            if llamadas >= max_llamadas:
                break
            llamadas += 1
            try:
                # OpenCode Go exige temperature=1 en algunos modelos; Ollama lo acepta igual.
                response = client.chat.completions.create(model=model, messages=messages, temperature=1,
                                                          max_tokens=8000 if origin == "Cloud" else 2000, **extra)
                raw = response.choices[0].message.content or ""
            except Exception as exc:
                errores.append(f"{origin}: {type(exc).__name__}: {exc}")
                break
            imposible = _motivo_imposible(raw)
            if imposible:
                from tools.registry import obtener_herramientas_relevantes
                utiles = [t["function"]["name"] for t in obtener_herramientas_relevantes(objetivo, True) or []
                          if t["function"]["name"] != "autoprogramar_habilidad"]
                sugerencia = (f" Herramientas integradas que sí sirven: {', '.join(utiles)}. Úsalas ahora."
                              if utiles else " Explícale a Cristhian qué falta.")
                return (f"No puedo aprender esto como habilidad: {imposible} Las habilidades aprendidas solo "
                        "calculan y trabajan con texto; no acceden a archivos, registro, comandos ni internet."
                        + sugerencia)
            try:
                propuesta = _extraer_propuesta(raw, nombre_sugerido)
                propuesta["nombre"] = _nombre_libre(propuesta["nombre"])
                _validate(propuesta["nombre"], propuesta["codigo"])
                ok, informe = _probar_en_aislado(propuesta["nombre"], propuesta["codigo"], propuesta["pruebas"])
                problema = None if ok else "Fallaron estas pruebas:\n" + "\n".join(informe)
            except Exception as exc:
                informe, problema = [], f"{type(exc).__name__}: {exc}"
            if problema is None:
                informe.append(f"Motor: {origin} ({model}) · intento {intento}/{intentos}")
                resultado = crear_y_cargar_herramienta(propuesta["nombre"], propuesta["descripcion"],
                                                       propuesta["codigo"], informe_pruebas=informe)
                if "cargada y registrada en caliente" not in resultado:
                    return resultado
                firma = f"{propuesta['nombre']}{_signature_from_ast(next(n for n in ast.parse(propuesta['codigo']).body if isinstance(n, ast.FunctionDef) and n.name == propuesta['nombre']))}"
                return (f"Habilidad aprendida y lista: {firma}. Superó {len(propuesta['pruebas'])} pruebas en el entorno aislado. "
                        f"Úsala ahora mismo para responder la petición original del usuario.")
            errores.append(f"{origin} intento {intento}: {problema[:300]}")
            if raw.strip():
                messages.append({"role": "assistant", "content": raw})
            messages += [{"role": "user", "content": f"Tu propuesta no sirve todavía. {problema}\n"
                                                     "Corrige el problema y devuelve otra vez los dos bloques (python y json), cumpliendo todas las reglas."}]
    if not errores:
        return "No se pudo forjar la habilidad: no hay ningún motor disponible (inicia Ollama o configura la API)."
    return "No se pudo forjar la habilidad tras varios intentos:\n- " + "\n- ".join(errores[-4:])


def reparar_habilidad(nombre: str) -> str:
    """Repara una habilidad aprendida usando el caso exacto que la rompió como prueba obligatoria."""
    from memory.learning_loop import ultimo_fallo

    nombre = (nombre or "").strip()
    ruta = CUSTOM_DIR / f"{nombre}.py"
    if not re.fullmatch(r"[A-Za-z_]\w*", nombre) or not ruta.is_file():
        return f"No conozco una habilidad aprendida llamada '{nombre}'."
    fallo = ultimo_fallo(nombre)
    if not fallo:
        return f"No tengo registrado ningún fallo de '{nombre}'; dime con qué datos falló."
    codigo = ruta.read_text(encoding="utf-8")
    objetivo = (
        f"Repara la habilidad existente `{nombre}`. Debe conservar el MISMO nombre de función y los mismos "
        f"parámetros. Código actual:\n```python\n{codigo}\n```\n"
        f"Falló al llamarla con {json.dumps(fallo.get('argumentos', {}), ensure_ascii=False)} → {fallo.get('error', '')[:400]}\n"
        f"Incluye OBLIGATORIAMENTE una prueba con esos mismos argumentos que ahora devuelva un resultado correcto "
        f"(o un mensaje claro en español si la entrada es inválida), además de las pruebas habituales."
    )
    from core import auditoria
    auditoria.registrar("habilidad", f"reparar {nombre}", fallo.get("error", "")[:200])
    return forjar_con_pruebas(objetivo, nombre)


def forjar_habilidad_desde_instruccion(instruccion: str) -> str:
    """Genera una habilidad desde `/autoprogramar` con pruebas automáticas."""
    match = re.search(r"(?:llamada|llamado|nombre|herramienta)\s+([A-Za-z_]\w*)", instruccion, re.IGNORECASE)
    return forjar_con_pruebas(instruccion, match.group(1) if match else "habilidad_generada")


def autoprogramar_habilidad(
    objetivo: str = "",
    nombre_funcion: str | None = None,
    codigo_python: str | None = None,
    nombre_habilidad: str | None = None,
    funcion: str | None = None,
    name: str | None = None,
    code: str | None = None,
    descripcion: str | None = None,
    **_kwargs,
) -> str:
    """Aprende una habilidad nueva; acepta los nombres de argumentos que suelen producir los modelos.

    Si el modelo ya envió código se valida y se pide confirmación; si no, se
    forja con pruebas automáticas y reparación.
    """
    nombre_funcion = nombre_funcion or nombre_habilidad or name
    codigo_entregado = codigo_python or funcion or code
    if codigo_entregado and not nombre_funcion:
        try:
            tree = ast.parse(codigo_entregado)
            nombre_funcion = next(node.name for node in tree.body if isinstance(node, ast.FunctionDef))
        except (SyntaxError, StopIteration):
            return "No se pudo inferir el nombre de la función entregada."
    objetivo = objetivo or descripcion or ""
    if codigo_entregado:
        return crear_y_cargar_herramienta(nombre_funcion, descripcion or objetivo or f"Habilidad {nombre_funcion}",
                                          codigo_entregado)
    if not objetivo and not nombre_funcion:
        return "Falta el objetivo: describe qué debe hacer la habilidad."
    return forjar_con_pruebas(objetivo or f"Habilidad {nombre_funcion}", nombre_funcion or "habilidad_generada")
