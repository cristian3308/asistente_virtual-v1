"""Interfaz interactiva de consola del asistente."""
from __future__ import annotations

import sys
import threading

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.live import Live
from rich.text import Text
from rich.table import Table

from config import settings
from core.brain import AssistantBrain
from memory.episodic_db import EpisodicMemory
from tools.memory_tools import buscar_en_memoria_profunda, indexar_proyecto_local
from tools.system_tools import estado_hardware
from core.sentinel import Sentinel
from core.self_coder import cargar_habilidades_guardadas, forjar_habilidad_desde_instruccion
from tools.registry import listar_habilidades_disponibles
from core.benchmark import medir_ollama

console = Console()


def main() -> None:
    brain = AssistantBrain()
    voice_enabled = False
    sentinel = Sentinel(voice_enabled=lambda: voice_enabled)
    if settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_ALLOWED_USER_ID:
        try:
            from interfaces.telegram_bot import run_telegram
            threading.Thread(target=run_telegram, args=(brain,), name="asistente-telegram", daemon=True).start()
            console.print("[green]Bot Telegram iniciado en segundo plano.[/green]")
        except Exception as exc:
            console.print(f"[yellow]Telegram no pudo iniciarse: {exc}[/yellow]")
    console.print(Panel.fit(
        "Asistente Híbrido — Windows · RTX 3050 · OpenCode Go / Ollama\n"
        f"Ollama: {'activo' if settings.ollama_activo() else 'apagado'} | Cloud: {'configurado' if settings.cloud_configurado() else 'sin API key'}\n"
        "Comandos: /estado /limpiar /indexar <ruta> /recuerdos /habilidades /cargar_habilidades /ver <pregunta> /centinela <on|off> /benchmark /modelo <codigo|razonamiento|rapido|local|turbo> /voz /salir",
        title="🤖 Asistente Virtual Profundo", border_style="cyan",
    ))
    while True:
        try:
            prompt = console.input("[bold green]Tú[/bold green] > ").strip()
            if not prompt:
                if voice_enabled:
                    try:
                        from voice.ear_stt import escuchar
                        console.print("[dim]Escuchando (máximo 5 segundos)...[/dim]")
                        prompt = escuchar()
                        if not prompt:
                            console.print("[yellow]No se detectó voz.[/yellow]")
                            continue
                        console.print(f"[green]Transcripción:[/green] {prompt}")
                    except Exception as exc:
                        console.print(f"[red]Error de micrófono/STT: {exc}[/red]")
                        continue
                else:
                    continue
            lower = prompt.lower()
            if lower in {"/salir", "/exit", "/quit"}:
                break
            if lower == "/limpiar":
                brain.clear_history()
                console.clear()
                console.print("[green]Historial de contexto limpiado; la memoria persistente se conserva.[/green]")
                continue
            if lower == "/estado":
                api_status = "🟢 ACTIVA" if settings.cloud_configurado() else "⚪ SIN CONFIGURAR (Usando 100% Local)"
                console.print(Panel(
                    f"{estado_hardware()}\n\nOpenCode Go API: {api_status}",
                    title="Estado del sistema", border_style="blue"
                ))
                continue
            if lower == "/voz":
                voice_enabled = not voice_enabled
                console.print(f"Voz {'activada: pulsa Enter para grabar y escribe /voz para desactivar.' if voice_enabled else 'desactivada.'}")
                continue
            if lower == "/benchmark":
                result = medir_ollama(brain.router)
                table = Table(title="Benchmark Ollama local")
                table.add_column("Métrica", style="cyan")
                table.add_column("Resultado", style="green")
                for key in ("ttft_ms", "ttft_real", "tok_s_total", "tok_s_generacion", "tokens", "chunks", "elapsed_s"):
                    if key in result:
                        table.add_row(key, str(result[key]))
                table.add_row("ollama ps", result.get("ollama_ps", result.get("error", "sin datos")))
                console.print(table)
                continue
            if lower.startswith("/autoprogramar"):
                instruction = prompt.partition(" ")[2].strip()
                if not instruction:
                    console.print("Uso: /autoprogramar <instrucción>")
                else:
                    forge_result = forjar_habilidad_desde_instruccion(instruction)
                    console.print(Panel(forge_result, title="Habilidad creada", border_style="green"))
                continue
            if lower == "/habilidades":
                console.print(Panel(listar_habilidades_disponibles(), title="Todas las habilidades", border_style="green"))
                continue
            if lower == "/cargar_habilidades":
                loaded = cargar_habilidades_guardadas()
                console.print(f"Habilidades cargadas: {', '.join(loaded) or '(ninguna)'}")
                continue
            if lower.startswith("/ver"):
                question = prompt.partition(" ")[2].strip()
                from tools.vision_tools import ver_pantalla_actual
                with console.status("Capturando y analizando pantalla..."):
                    ocr_text = ver_pantalla_actual()
                    analysis_prompt = (
                        f"Analiza el texto extraído de mi pantalla y responde directamente a esta pregunta: {question or '¿Qué observas?'}\n\n"
                        f"Texto OCR:\n{ocr_text}"
                    )
                    answer, motor = brain.ask(analysis_prompt)
                console.print(Panel(answer, title=f"Análisis de pantalla · {motor}", border_style="yellow"))
                continue
            if lower.startswith("/centinela"):
                action = prompt.partition(" ")[2].strip().lower()
                if action == "on":
                    sentinel.start()
                    console.print("[green]Centinela activado.[/green]")
                elif action == "off":
                    sentinel.stop()
                    console.print("[yellow]Centinela detenido.[/yellow]")
                else:
                    console.print("Uso: /centinela on|off")
                continue
            if lower.startswith("/modelo"):
                arg = prompt.partition(" ")[2].strip()
                console.print(brain.router.set_model(arg) if arg else "Uso: /modelo codigo|razonamiento|rapido|local")
                continue
            if lower.startswith("/indexar"):
                path = prompt.partition(" ")[2].strip().strip('"')
                if not path:
                    console.print("Uso: /indexar <ruta>")
                else:
                    with console.status("Indexando proyecto en CPU..."):
                        console.print(indexar_proyecto_local(path))
                continue
            if lower == "/recuerdos":
                records = EpisodicMemory().recent_records(12)
                found = buscar_en_memoria_profunda("preferencias proyectos información personal")
                console.print(Panel(f"[bold]Recuerdos semánticos[/bold]\n{found}\n\n[bold]Mensajes recientes[/bold]\n" + "\n".join(
                    f"{stamp[:19]} [{motor or '—'}] {text[:180]}" for stamp, text, motor in records
                ), title="Memoria", border_style="magenta"))
                continue
            visible = []
            speaker = None
            if voice_enabled:
                try:
                    from voice.mouth_tts import SentenceSpeaker
                    speaker = SentenceSpeaker()
                except Exception:
                    speaker = None

            def on_token(token: str) -> None:
                visible.append(token)
                if speaker:
                    speaker.feed(token)
                live.update(Text("".join(visible)))

            with Live(Text("Pensando..."), console=console, refresh_per_second=20) as live:
                answer, motor = brain.ask(prompt, on_token=on_token)
                live.update(Markdown(answer))
            if speaker:
                speaker.close()
            console.print(f"[dim]Motor: {motor}[/dim]")
        except (KeyboardInterrupt, EOFError):
            break
    console.print("[dim]Cerrando asistente.[/dim]")


if __name__ == "__main__":
    main()
