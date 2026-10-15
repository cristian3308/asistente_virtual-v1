"""Banco de pruebas: ¿qué modelo local elige mejor las herramientas del asistente?

Usa el mismo camino que producción (system prompt, filtro de herramientas,
`_payload_for` con recorte de contexto y opciones de Ollama), pero NUNCA
ejecuta herramientas: solo registra cuál pidió el modelo.

Uso:
    .venv\\Scripts\\python.exe benchmarks\\modelos_herramientas.py
    .venv\\Scripts\\python.exe benchmarks\\modelos_herramientas.py --modelos qwen3:4b qwen2.5-coder:3b --num-ctx 4096
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rich.console import Console  # noqa: E402
from rich.markup import escape  # noqa: E402
from rich.table import Table  # noqa: E402

from config import settings  # noqa: E402
from core import self_coder  # noqa: E402
from core.brain import AssistantBrain  # noqa: E402
from core.router import ModelRouter, Motor  # noqa: E402
from tools.registry import FUNCTIONS, obtener_herramientas_relevantes  # noqa: E402

console = Console()

# (pregunta, herramienta esperada o None, texto que debe aparecer en los argumentos)
CASOS: list[tuple[str, str | None, str | None]] = [
    ("¿Cuánta RAM estoy usando ahora?", "estado_hardware", None),
    ("¿Cómo está la temperatura de la GPU?", "estado_hardware", None),
    ("¿Qué procesos consumen más memoria?", "listar_procesos_pesados", None),
    ("¿Qué puertos tengo abiertos en mi PC?", "auditar_puertos_locales", None),
    ("Abre Discord", "abrir_aplicacion", "discord"),
    ("abre la calculadora", "abrir_aplicacion", "calc"),
    ("Lee lo que tengo copiado en el portapapeles", "leer_portapapeles", None),
    ("Recuérdame en 10 minutos revisar el horno", "programar_recordatorio", "10"),
    ("Busca en internet cuál es la última versión de Python", "buscar_en_internet", "python"),
    ("¿Qué archivos hay en la carpeta tools del proyecto?", "explorar_directorio", "tools"),
    ("Guarda una nota en Obsidian que diga: comprar leche", "crear_o_actualizar_nota", "leche"),
    ("¿Qué habilidades tienes?", "listar_habilidades_disponibles", None),
    ("Hola, ¿cómo estás?", None, None),
    ("Explícame en una frase qué es una variable en Python", None, None),
    ("Gracias, eso es todo por hoy", None, None),
]


def registrar_habilidades_aprobadas() -> None:
    """Registra solo habilidades aprobadas cuyo hash coincide; no ejecuta su código."""
    import hashlib

    for item in self_coder._manifest():
        path = self_coder.CUSTOM_DIR / str(item.get("file", ""))
        if not path.is_file() or item.get("approved") is not True:
            continue
        digest = hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
        if digest != str(item.get("sha256", "")).lower():
            continue
        self_coder._register(item["name"], item.get("description", ""), self_coder._load(item["name"], path))


def modelos_instalados() -> list[str]:
    salida = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=20).stdout
    return [linea.split()[0] for linea in salida.splitlines()[1:] if linea.strip()]


def vram_de(modelo: str) -> str:
    try:
        salida = subprocess.run(["ollama", "ps"], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return "?"
    for linea in salida.splitlines()[1:]:
        if linea.startswith(modelo + " ") or linea.split()[:1] == [modelo]:
            partes = re.split(r"\s{2,}", linea.strip())
            # NAME, ID, SIZE, PROCESSOR, CONTEXT, ...
            return f"{partes[2]} · {partes[3]}" + (f" · ctx {partes[4]}" if len(partes) > 4 else "")
    return "no cargado"


def primer_json(texto: str) -> dict | None:
    """Extrae el primer objeto JSON aunque el modelo añada texto detrás."""
    inicio = texto.find("{")
    if inicio < 0:
        return None
    try:
        valor, _fin = json.JSONDecoder().raw_decode(texto[inicio:])
    except json.JSONDecodeError:
        return None
    return valor if isinstance(valor, dict) else None


def evaluar(router: ModelRouter, modelo: str, system_prompt: str, pregunta: str) -> dict:
    motor = Motor(router.local, modelo, "Local")
    herramientas = obtener_herramientas_relevantes(pregunta, True)
    kwargs: dict = {"messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": pregunta}]}
    if herramientas:
        kwargs["tools"] = herramientas
        kwargs["tool_choice"] = "auto"
    payload = router._payload_for(motor, kwargs)
    ofrecidas = [t["function"]["name"] for t in herramientas or []]
    inicio = time.perf_counter()
    try:
        respuesta = router.local.chat.completions.create(model=modelo, temperature=0, **payload)
    except Exception as exc:  # p. ej. modelos sin soporte de tools
        return {"ofrecidas": ofrecidas, "error": f"{type(exc).__name__}: {str(exc)[:120]}", "segundos": time.perf_counter() - inicio}
    segundos = time.perf_counter() - inicio
    mensaje = respuesta.choices[0].message
    texto = re.sub(r"<think>.*?</think>", "", mensaje.content or "", flags=re.DOTALL).strip()
    resultado = {"ofrecidas": ofrecidas, "segundos": segundos, "texto": texto[:200], "modo": "ninguna", "herramienta": None, "args": ""}
    if mensaje.tool_calls:
        llamada = mensaje.tool_calls[0]
        resultado.update(modo="nativa", herramienta=llamada.function.name, args=llamada.function.arguments or "")
        return resultado
    candidato = primer_json(texto)
    if candidato and isinstance(candidato.get("name"), str) and candidato["name"] in FUNCTIONS:
        capturado_hoy = AssistantBrain._parse_text_tool_call(texto) is not None
        resultado.update(
            modo="texto (parser OK)" if capturado_hoy else "texto (parser FALLA)",
            herramienta=candidato["name"],
            args=json.dumps(candidato.get("arguments", candidato.get("args", {})), ensure_ascii=False),
        )
    return resultado


def puntuar(caso: tuple[str, str | None, str | None], r: dict) -> tuple[bool, bool]:
    """Devuelve (eligió bien, el asistente lo ejecutaría hoy)."""
    _pregunta, esperada, pista = caso
    if "error" in r:
        return False, False
    if esperada is None:
        return r["herramienta"] is None, r["herramienta"] is None
    acierto = r["herramienta"] == esperada and (pista is None or pista.lower() in r["args"].lower())
    ejecutable = acierto and r["modo"] in {"nativa", "texto (parser OK)"}
    return acierto, ejecutable


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--modelos", nargs="*", help="Modelos de Ollama a comparar (por defecto: todos los instalados)")
    parser.add_argument("--num-ctx", type=int, default=settings.OLLAMA_EXTRA_BODY["options"]["num_ctx"])
    args = parser.parse_args()

    if not settings.ollama_activo():
        console.print("[red]Ollama no responde en 127.0.0.1:11434.[/red]")
        sys.exit(1)
    settings.OLLAMA_EXTRA_BODY["options"]["num_ctx"] = args.num_ctx
    registrar_habilidades_aprobadas()
    with contextlib.redirect_stdout(io.StringIO()):
        system_prompt = AssistantBrain().system_prompt
    router = ModelRouter()
    modelos = args.modelos or modelos_instalados()
    console.print(f"[bold]Banco de pruebas[/bold] · {len(modelos)} modelos × {len(CASOS)} casos · num_ctx {args.num_ctx}\n")

    resumen, detalle = [], {}
    for modelo in modelos:
        console.print(f"[cyan]→ {modelo}[/cyan] cargando...", end=" ")
        carga = time.perf_counter()
        try:
            router.local.chat.completions.create(model=modelo, messages=[{"role": "user", "content": "OK"}], max_tokens=1,
                                                 extra_body=settings.OLLAMA_EXTRA_BODY)
        except Exception as exc:
            console.print(f"[red]no se pudo cargar: {exc}[/red]")
            continue
        console.print(f"{time.perf_counter() - carga:.1f}s")
        resultados = []
        for caso in CASOS:
            r = evaluar(router, modelo, system_prompt, caso[0])
            r["acierto"], r["ejecutable"] = puntuar(caso, r)
            resultados.append(r)
            marca = "[green]✓[/green]" if r["ejecutable"] else ("[yellow]~[/yellow]" if r["acierto"] else "[red]✗[/red]")
            etiqueta = escape(f"{r.get('herramienta') or r.get('error', '—')} [{r.get('modo', 'error')}]")
            console.print(f"   {marca} {caso[0][:45]:45} → {etiqueta} {r['segundos']:.1f}s")
            if not r["acierto"] and r.get("texto"):
                console.print(f"      [dim]{escape(r['texto'][:110])!r}[/dim]")
        detalle[modelo] = resultados
        con_tool = [r for r, c in zip(resultados, CASOS) if c[1]]
        sin_tool = [r for r, c in zip(resultados, CASOS) if not c[1]]
        resumen.append({
            "modelo": modelo,
            "elige_bien": sum(r["acierto"] for r in con_tool),
            "ejecuta_hoy": sum(r["ejecutable"] for r in con_tool),
            "total_tool": len(con_tool),
            "charla_ok": sum(r["acierto"] for r in sin_tool),
            "total_charla": len(sin_tool),
            "parser_falla": sum(r.get("modo") == "texto (parser FALLA)" for r in resultados),
            "errores": sum("error" in r for r in resultados),
            "mediana_s": statistics.median(r["segundos"] for r in resultados),
            "vram": vram_de(modelo),
        })

    tabla = Table(title=f"Resultados (num_ctx {args.num_ctx})")
    for col in ("Modelo", "Elige bien", "Se ejecutaría hoy", "Charla sin tools", "JSON perdido por parser", "Errores", "Mediana", "VRAM"):
        tabla.add_column(col)
    for f in sorted(resumen, key=lambda x: (-x["ejecuta_hoy"], -x["elige_bien"], x["mediana_s"])):
        tabla.add_row(f["modelo"], f"{f['elige_bien']}/{f['total_tool']}", f"{f['ejecuta_hoy']}/{f['total_tool']}",
                      f"{f['charla_ok']}/{f['total_charla']}", str(f["parser_falla"]), str(f["errores"]),
                      f"{f['mediana_s']:.1f}s", f["vram"])
    console.print(tabla)

    filtro = [(c[0], c[1]) for c, r in zip(CASOS, next(iter(detalle.values()), [])) if c[1] and c[1] not in r["ofrecidas"]]
    if filtro:
        console.print("\n[yellow]El filtro de herramientas NO ofreció la herramienta esperada en:[/yellow]")
        for pregunta, esperada in filtro:
            console.print(f"   · {pregunta!r} (esperaba {esperada})")

    salida = settings.DATA_DIR / "benchmarks"
    salida.mkdir(parents=True, exist_ok=True)
    archivo = salida / f"modelos_{datetime.now():%Y%m%d_%H%M}_ctx{args.num_ctx}.json"
    archivo.write_text(json.dumps({"resumen": resumen, "detalle": detalle, "casos": CASOS}, ensure_ascii=False, indent=2), encoding="utf-8")
    console.print(f"\n[dim]Detalle guardado en {archivo}[/dim]")


if __name__ == "__main__":
    main()
