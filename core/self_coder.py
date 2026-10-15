"""Forja de herramientas Python con validación estática e importación en caliente.

El código generado nunca se ejecuta antes de pasar las comprobaciones AST y las
dependencias externas siempre requieren confirmación explícita.
"""
from __future__ import annotations

import ast
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


def _forge_response(result: str, name: str, code: str, origin: str, model: str) -> str:
    """No presenta como aprobada una habilidad que el usuario rechazó."""
    if "cargada y registrada en caliente" not in result:
        return result
    path = CUSTOM_DIR / f"{name}.py"
    return f"{result}\nRuta: {path}\n\nCódigo generado:\n{code}\n\nConfirmado: aparece en /habilidades. Motor: {origin} ({model})"


def crear_y_cargar_herramienta(
    nombre_funcion: str,
    descripcion: str,
    codigo_python: str,
    paquetes_pip: list[str] | None = None,
) -> str:
    """Valida y carga una habilidad solo tras confirmación interactiva explícita."""
    paquetes_pip = paquetes_pip or []
    _validate(nombre_funcion, codigo_python)
    if not confirmation_allowed():
        return "Habilidad rechazada: las confirmaciones solo están disponibles desde la consola local."
    Console().print(Syntax(codigo_python, "python", line_numbers=True, theme="monokai"))
    if not Confirm.ask(
        f"¿Autorizas guardar e importar la habilidad generada '{nombre_funcion}'?",
        default=False,
    ):
        return "Habilidad rechazada: no se guardó ni se ejecutó código generado."
    if paquetes_pip:
        clean_packages = [p for p in paquetes_pip if re.fullmatch(r"[A-Za-z0-9_.-]+(?:==[A-Za-z0-9_.-]+)?", p)]
        if len(clean_packages) != len(paquetes_pip):
            return "Paquetes rechazados: nombre inválido."
        if not Confirm.ask(f"¿Instalar dependencias para {nombre_funcion}: {', '.join(clean_packages)}?", default=False):
            return "Instalación cancelada; no se creó la habilidad."
        pip_path = settings.ROOT_DIR / ".venv" / "Scripts" / "pip.exe"
        result = subprocess.run([str(pip_path), "install", *clean_packages], shell=False, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            return f"Falló pip: {result.stderr[-1500:]}"
    CUSTOM_DIR.mkdir(parents=True, exist_ok=True)
    path = CUSTOM_DIR / f"{nombre_funcion}.py"
    path.write_text(codigo_python.rstrip() + "\n", encoding="utf-8")
    function = _load(nombre_funcion, path)
    _register(nombre_funcion, descripcion, function)
    items = [item for item in _manifest() if item.get("name") != nombre_funcion]
    items.append({
        "name": nombre_funcion,
        "description": descripcion,
        "file": path.name,
        "sha256": hashlib.sha256(codigo_python.encode("utf-8")).hexdigest(),
        "approved": True,
    })
    _save_manifest(items)
    return f"Habilidad '{nombre_funcion}' validada, cargada y registrada en caliente."


def cargar_habilidades_guardadas() -> list[str]:
    """Carga habilidades persistidas solo cuando el usuario lo solicita explícitamente."""
    loaded = []
    for path in sorted(CUSTOM_DIR.glob("*.py")) if CUSTOM_DIR.exists() else []:
        if path.name == "__init__.py":
            continue
        name = path.stem
        try:
            code = path.read_text(encoding="utf-8")
            item = next((x for x in _manifest() if x.get("name") == name), {})
            digest = hashlib.sha256(code.encode("utf-8")).hexdigest()
            trusted = item.get("approved") is True and str(item.get("sha256", "")).lower() == digest
            if not trusted:
                _validate(name, code)
            if not confirmation_allowed():
                continue
            Console().print(Syntax(code, "python", line_numbers=True, theme="monokai"))
            if not Confirm.ask(f"¿Autorizas importar la habilidad guardada '{name}'?", default=False):
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


def forjar_habilidad_desde_instruccion(instruccion: str) -> str:
    """Genera una habilidad desde `/autoprogramar` y la instala de forma verificable."""
    from core.router import ModelRouter
    router = ModelRouter()
    suggested = "habilidad_generada"
    match = re.search(r"(?:llamada|llamado|llamada|nombre)\s+([A-Za-z_]\w*)", instruccion, re.IGNORECASE)
    if not match:
        match = re.search(r"herramienta\s+([A-Za-z_]\w*)", instruccion, re.IGNORECASE)
    if match:
        suggested = match.group(1)
    prompt = (
        "Devuelve EXCLUSIVAMENTE un JSON válido con las claves nombre_funcion, descripcion y codigo_python. "
        "codigo_python debe contener una función Python completa, tipada, con docstring y retorno str. "
        "Usa por defecto la firma base ruta_archivo: str = '', path: str = '', file_path: str = '', **kwargs y la primera ruta no vacía cuando aplique. "
        "No uses subprocess, os.system, eval, exec, borrado, formateo, credenciales ni comandos destructivos. "
        f"La función debe llamarse {suggested}. Instrucción: {instruccion}"
    )
    responses = []
    if settings.cloud_configurado():
        responses.append((router.cloud, router.cloud_model, "Cloud"))
    responses.append((router.local, settings.MODEL_LOCAL, "Local"))
    errors = []
    for client, model, origin in responses:
        try:
            # OpenCode Go exige temperature=1 para este modelo; Ollama también
            # funciona correctamente con el valor por defecto.
            kwargs = {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 1, "max_tokens": 1600}
            if origin == "Local":
                kwargs["extra_body"] = {**settings.OLLAMA_EXTRA_BODY, "think": False}
            response = client.chat.completions.create(**kwargs)
            name, description, code = _extraer_codigo_forjado(response.choices[0].message.content or "", suggested)
            result = crear_y_cargar_herramienta(name, description, code)
            return _forge_response(result, name, code, origin, model)
        except Exception as exc:
            # Reintento de reparación: algunos modelos locales devuelven JSON
            # truncado o mezclan explicación con el código solicitado.
            try:
                repair_prompt = (
                    f"Devuelve SOLO código Python válido, sin JSON, markdown ni explicación. Define "
                    f"def {suggested}(ruta_archivo: str = '', path: str = '', file_path: str = '', **kwargs) -> str. "
                    f"Objetivo: {instruccion}"
                )
                repair_kwargs = {"model": model, "messages": [{"role": "user", "content": repair_prompt}], "temperature": 1, "max_tokens": 1600}
                if origin == "Local":
                    repair_kwargs["extra_body"] = {**settings.OLLAMA_EXTRA_BODY, "think": False}
                repaired = client.chat.completions.create(**repair_kwargs)
                repaired_text = repaired.choices[0].message.content or ""
                name, description, code = _extraer_codigo_forjado(repaired_text, suggested)
                result = crear_y_cargar_herramienta(name, description, code)
                return _forge_response(result, name, code, origin, model)
            except Exception as repair_exc:
                errors.append(f"{origin}: {type(exc).__name__}: {exc}; reparación: {type(repair_exc).__name__}: {repair_exc}")
    return "No se pudo forjar la habilidad: " + " | ".join(errors)


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
    """Forja una habilidad aceptando los nombres de argumentos que suelen producir los modelos locales.

    Si el modelo ya envió código (`funcion`, `codigo_python` o `code`), se valida
    y registra directamente sin hacer otra llamada al proveedor cloud.
    """
    nombre_funcion = nombre_funcion or nombre_habilidad or name
    codigo_entregado = codigo_python or funcion or code
    if codigo_entregado and not nombre_funcion:
        try:
            tree = ast.parse(codigo_entregado)
            nombre_funcion = next(node.name for node in tree.body if isinstance(node, ast.FunctionDef))
        except (SyntaxError, StopIteration):
            return "No se pudo inferir el nombre de la función entregada."
    if not nombre_funcion:
        return "Falta nombre_funcion (también acepto nombre_habilidad o name)."
    objetivo = objetivo or descripcion or f"Habilidad {nombre_funcion}"
    if codigo_entregado:
        return crear_y_cargar_herramienta(
            nombre_funcion, descripcion or objetivo, codigo_entregado
        )

    """Solicita al modelo Cloud código para un objetivo y lo instala tras validarlo."""
    from core.router import ModelRouter
    router = ModelRouter()
    prompt = (
        "Escribe una única herramienta Python segura para Windows. Devuelve SOLO código Python, sin markdown. "
        f"Debe definir exactamente def {nombre_funcion}(ruta_archivo: str = '', path: str = '', file_path: str = '', **kwargs) -> str y devolver un resultado textual. "
        "Para rutas usa la primera opción no vacía entre ruta_archivo, path, file_path y kwargs. "
        "No uses subprocess, os.system, eval, exec, borrado, formateo ni acceso a secretos. "
        f"Objetivo del usuario: {objetivo}"
    )
    try:
        response = router.cloud.chat.completions.create(
            model=router.cloud_model, messages=[{"role": "user", "content": prompt}], temperature=1
        )
        code = response.choices[0].message.content or ""
        match = re.search(r"```(?:python)?\s*(.*?)```", code, re.DOTALL | re.IGNORECASE)
        code = match.group(1).strip() if match else code.strip()
        return crear_y_cargar_herramienta(nombre_funcion, objetivo, code)
    except Exception as exc:
        return f"No se pudo forjar la habilidad: {type(exc).__name__}: {exc}"
