"""Interfaz interactiva de consola del asistente."""
from __future__ import annotations

import json
import sys
import threading
from contextlib import contextmanager

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.live import Live
from rich.text import Text
from rich.syntax import Syntax
from rich.table import Table

from config import settings
from core.brain import AssistantBrain
from memory.episodic_db import EpisodicMemory
from tools.memory_tools import buscar_en_memoria_profunda, indexar_proyecto_local
from tools.system_tools import estado_hardware
from core.sentinel import Sentinel
from core.self_coder import cargar_habilidades_guardadas, confirmar as confirmar_consola, forjar_habilidad_desde_instruccion, reset_ui_pause, set_ui_pause
from tools.registry import listar_habilidades_disponibles
from core.benchmark import medir_ollama
from interfaces import avatar

console = Console()
CODIGO_REINICIO = 3  # iniciar_asistente.bat relanza el asistente con este código de salida


def main() -> None:
    brain = AssistantBrain()
    loaded_skills = cargar_habilidades_guardadas()
    if settings.AVATAR:
        console.print(f"[dim]{avatar.iniciar()}[/dim]")
    if loaded_skills:
        console.print(f"[green]Habilidades aprobadas cargadas:[/green] {', '.join(loaded_skills)}")
    voice_enabled = False
    sentinel = Sentinel(voice_enabled=lambda: voice_enabled)
    from core import tareas
    from interfaces import notificaciones
    notificaciones.voz_activa = lambda: voice_enabled
    # Cerebro propio para el segundo plano: no comparte historial ni candado con la consola.
    motor_tareas = tareas.MotorTareas(crear_cerebro=AssistantBrain, notificar=notificaciones.notificar)
    from tools.system_tools import iniciar_vigilancia_ventanas
    iniciar_vigilancia_ventanas()  # recuerda en qué ventana estabas antes de escribirle
    recuperadas = motor_tareas.iniciar()
    pendientes = tareas.listar()
    if recuperadas or pendientes:
        console.print(f"[cyan]Tareas: {len(pendientes)} pendiente(s)"
                      + (f", {recuperadas} reanudada(s) tras el reinicio" if recuperadas else "") + ". /tareas para verlas.[/cyan]")
    if settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_ALLOWED_USER_ID:
        try:
            from interfaces.telegram_bot import run_telegram
            threading.Thread(target=run_telegram, args=(brain,), name="asistente-telegram", daemon=True).start()
            console.print("[dim]Conectando con Telegram...[/dim]")
        except Exception as exc:
            console.print(f"[yellow]Telegram no pudo iniciarse: {exc}[/yellow]")
    console.print(Panel.fit(
        "Asistente Híbrido — Windows · RTX 3050 · OpenCode Go / Ollama\n"
        f"Ollama: {'activo' if settings.ollama_activo() else 'apagado'} | Cloud: {'configurado' if settings.cloud_configurado() else 'sin API key'}\n"
        "Comandos: /estado /limpiar /indexar <ruta> /recuerdos /habilidades /cargar_habilidades /ver <pregunta> /centinela <on|off> /benchmark /modelo <codigo|razonamiento|rapido|local|turbo> /tareas /tarea <objetivo> /cancelar /pausar /reactivar /programar <cambio> /revisar /aprobar /rechazar /deshacer /olvidar /auditoria /fallos /procedimientos /reiniciar /parar /reanudar /voz /voces /voz_probar /voz_usar /conversar /avatar /salir",
        title="🤖 Asistente Virtual Profundo", border_style="cyan",
    ))

    def responder(prompt: str) -> None:
        """Genera una respuesta y, si corresponde, la reproduce completa."""
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

        @contextmanager
        def pausar_live():
            # Las confirmaciones (forja, PowerShell, navegador) necesitan la consola quieta.
            live.stop()
            try:
                yield
            finally:
                live.start()

        try:
            with Live(Text("Pensando..."), console=console, refresh_per_second=20) as live:
                pause_token = set_ui_pause(pausar_live)
                try:
                    answer, motor = brain.ask(prompt, on_token=on_token)
                finally:
                    reset_ui_pause(pause_token)
                live.update(Markdown(answer))
        finally:
            if speaker:
                # También actúa como silenciador: el siguiente escuchar() espera aquí.
                speaker.close()
        console.print(f"[dim]Motor: {motor}[/dim]")

    def conversar() -> None:
        """Bucle de conversación manos libres; termina con 'salir'."""
        nonlocal voice_enabled
        voice_enabled = True
        try:
            from voice.ear_stt import escuchar, precargar
            precargar()
            console.print(f"[green]Conversación activa. Habla; respondo cuando te calles "
                          f"{settings.VOZ_SILENCIO_FIN:g} s. Di 'salir' para terminar.[/green]")
            while True:
                console.print("[dim]Escuchando...[/dim]")
                prompt = escuchar()
                if not prompt:
                    continue
                console.print(f"[green]Transcripción:[/green] {prompt}")
                if prompt.strip().lower().strip(" .,!¡¿?") in {"salir", "terminar", "adiós", "adios", "para", "detente"}:
                    break
                responder(prompt)
        except Exception as exc:
            console.print(f"[red]Error de conversación/STT: {exc}[/red]")
        finally:
            voice_enabled = False
            console.print("[yellow]Conversación terminada.[/yellow]")

    while True:
        try:
            prompt = console.input("[bold green]Tú[/bold green] > ").strip()
            if not prompt:
                if voice_enabled:
                    try:
                        from voice.ear_stt import escuchar
                        console.print("[dim]Escuchando... (termino cuando dejes de hablar)[/dim]")
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
            if lower == "/voces":
                from voice.mouth_tts import listar_voces
                console.print(Panel(listar_voces() + "\n\nPrueba: /voz_probar jarvis · Elegir: /voz_usar jarvis",
                                    title="Voces (▶ = actual)", border_style="cyan"))
                continue
            if lower.startswith("/voz_probar"):
                from voice.mouth_tts import hablar, voz_actual
                nombre = prompt.partition(" ")[2].strip() or voz_actual()
                console.print(f"[dim]Probando la voz '{nombre}'...[/dim]")
                try:
                    hablar("Buenas, Cristhian. Todos los sistemas están en línea. ¿En qué te ayudo hoy?", voz=nombre)
                except Exception as exc:
                    console.print(f"[red]No se pudo probar '{nombre}': {exc}[/red]")
                continue
            if lower.startswith("/voz_usar"):
                from voice.mouth_tts import elegir_voz
                console.print(elegir_voz(prompt.partition(" ")[2]))
                continue
            if lower == "/voz":
                voice_enabled = not voice_enabled
                if voice_enabled:
                    from voice.ear_stt import precargar
                    precargar()
                console.print(f"Voz {'activada: pulsa Enter para grabar y escribe /voz para desactivar.' if voice_enabled else 'desactivada.'}")
                continue
            if lower == "/avatar":
                console.print(avatar.detener() if avatar.abierto() else avatar.iniciar())
                continue
            if lower == "/conversar":
                conversar()
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
                        f"Texto OCR:\n{ocr_text[:3000]}"
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
                from memory import perfil
                datos = perfil.hechos()
                tabla = Table(title="Lo que sé de ti (se incluye en cada respuesta)")
                for columna in ("id", "dato", "valor", "categoría", "actualizado"):
                    tabla.add_column(columna)
                for h in datos:
                    tabla.add_row(str(h["id"]), h["clave"], h["valor"], h["categoria"], h["actualizado"][:10])
                console.print(tabla if datos else "[dim]Aún no sé nada de ti: cuéntame (\"me llamo…\", \"me gusta…\").[/dim]")
                console.print("[dim]Corregir: dímelo de nuevo (\"mi mamá se llama …\"). Borrar: /olvidar <id o texto> o \"olvida que …\".[/dim]")
                continue
            if lower in {"/parar", "/stop", "/detener"}:
                from core import auditoria
                sentinel.stop()
                console.print(f"[bold red]{auditoria.detener('consola')}[/bold red]")
                continue
            if lower in {"/reanudar", "/continuar"}:
                from core import auditoria
                console.print(f"[green]{auditoria.reanudar()}[/green]")
                continue
            if lower.startswith("/tareas"):
                tabla = Table(title="Tareas (/tareas todas: incluye terminadas)")
                for columna in ("id", "tipo", "estado", "cuándo", "objetivo", "intentos", "próximo paso / resultado"):
                    tabla.add_column(columna, overflow="fold")
                for t in tareas.listar(incluir_terminadas="todas" in lower):
                    tabla.add_row(t["id"], t["tipo"], t["estado"], (t["programada_para"] or "")[5:16].replace("T", " "),
                                  t["objetivo"][:50], f"{t['intentos']}/{t['max_intentos']}",
                                  (t["proximo_paso"] or t["resultado"] or t["error"] or "")[:70])
                console.print(tabla if tabla.rows else "[dim]No hay tareas. Crea una con /tarea <objetivo> o pide un recordatorio.[/dim]")
                continue
            if lower.startswith("/tarea "):
                id_tarea = tareas.crear("agente", prompt.partition(" ")[2])
                console.print(f"[green]Tarea [{id_tarea}] en cola: la hago en segundo plano y te aviso al terminar.[/green]")
                continue
            for comando, accion, texto in (("/cancelar", tareas.cancelar, "cancelada"), ("/pausar", tareas.pausar, "pausada"),
                                           ("/reactivar", tareas.continuar, "reactivada")):
                if lower.startswith(comando + " "):
                    id_tarea = prompt.partition(" ")[2].strip("[] ")
                    console.print(f"Tarea {id_tarea} {texto}." if accion(id_tarea) else f"No pude: revisa el id con /tareas.")
                    break
            else:
                comando = None
            if comando:
                continue
            if lower.startswith("/programar "):
                from tools.registry import call_tool
                console.print(call_tool("programar_cambio", json.dumps({"objetivo": prompt.partition(" ")[2]})))
                continue
            if lower.startswith(("/revisar ", "/aprobar ", "/rechazar ", "/deshacer ")):
                from core import programador
                comando, _, id_tarea = prompt.partition(" ")
                id_tarea = id_tarea.strip("[] ")
                tarea = tareas.obtener(id_tarea)
                if not tarea or tarea["tipo"] != "programa":
                    console.print("[yellow]No hay un cambio de código con ese id. Míralos con /tareas.[/yellow]")
                    continue
                extra = tareas.datos(tarea)
                try:
                    if comando.lower() == "/aprobar" and not extra:
                        console.print("Cambio aprobado: el agente empieza en segundo plano y te aviso al terminar."
                                      if tareas.autorizar_inicio(id_tarea) else "Ese cambio no está esperando aprobación para empezar.")
                    elif comando.lower() == "/revisar":
                        texto = programador.diff(id_tarea)
                        console.print(Panel(tarea["resultado"] or "", title=f"Cambio {id_tarea}: {tarea['objetivo'][:60]}",
                                            border_style="cyan"))
                        console.print(Syntax(texto or "(sin cambios)", "diff", line_numbers=False, word_wrap=True))
                        avisos = programador.avisos_de_seguridad(texto)
                        if avisos:
                            console.print(Panel("\n".join(avisos[:30]), title="⚠ Revisa con cuidado: toca seguridad, comandos o secretos",
                                                border_style="red"))
                        console.print(f"[dim]/aprobar {id_tarea} para aplicarlo · /rechazar {id_tarea} para descartarlo[/dim]")
                    elif comando.lower() == "/aprobar":
                        if tarea["estado"] != "esperando_autorizacion":
                            console.print("Ese cambio no está esperando revisión.")
                        elif not extra.get("pruebas_ok") and not confirmar_consola("⚠ Las pruebas FALLAN con este cambio. ¿Aplicarlo de todos modos?"):
                            console.print("No se aplicó.")
                        elif confirmar_consola(f"¿Aplicar a tu código los cambios en {', '.join(extra.get('archivos', []))}?"):
                            merge = programador.aprobar(id_tarea)
                            tareas._actualizar(id_tarea, "aplicado por el usuario", estado="completada", proximo_paso=None,
                                               datos=json.dumps({**extra, "merge": merge}))
                            console.print(f"[green]Aplicado (commit {merge[:7]}). Escribe /reiniciar para usarlo ya. "
                                          f"Si algo va mal: /deshacer {id_tarea}[/green]")
                    elif comando.lower() == "/rechazar":
                        programador.rechazar(id_tarea)
                        tareas._actualizar(id_tarea, "rechazado por el usuario", estado="cancelada", proximo_paso=None)
                        console.print(f"Cambio {id_tarea} descartado; tu código no se tocó.")
                    elif comando.lower() == "/deshacer":
                        if not extra.get("merge"):
                            console.print("Ese cambio no se ha aplicado, no hay nada que deshacer.")
                        else:
                            revert = programador.deshacer(extra["merge"])
                            tareas._actualizar(id_tarea, "deshecho por el usuario", datos=json.dumps({**extra, "revert": revert}))
                            console.print(f"[green]Cambio deshecho (commit {revert[:7]}). Reinicia el asistente.[/green]")
                except Exception as exc:
                    console.print(f"[red]No se pudo: {exc}[/red]")
                continue
            if lower == "/fallos":
                from memory.learning_loop import fallos_recientes
                tabla = Table(title="Últimos fallos de herramientas (repáralos con: repara la habilidad <nombre>)")
                for columna in ("fecha", "herramienta", "argumentos", "error"):
                    tabla.add_column(columna, overflow="fold")
                for f in fallos_recientes(15):
                    tabla.add_row(f["fecha"][5:16], f["herramienta"], json.dumps(f.get("argumentos", ""), ensure_ascii=False)[:50],
                                  f["error"][:90])
                console.print(tabla if tabla.rows else "[dim]Sin fallos registrados.[/dim]")
                continue
            if lower == "/procedimientos":
                from memory import procedimientos
                tabla = Table(title="Procedimientos aprendidos (recetas que funcionaron)")
                for columna in ("id", "para", "pasos", "éxitos", "fallos"):
                    tabla.add_column(columna, overflow="fold")
                for p in procedimientos.listar():
                    tabla.add_row(str(p["id"]), p["objetivo"][:60], " → ".join(x["herramienta"] for x in json.loads(p["pasos"])),
                                  str(p["exitos"]), str(p["fallos"]))
                console.print(tabla if tabla.rows else "[dim]Aún no aprendí procedimientos: aparecen al resolver algo con varias herramientas.[/dim]")
                continue
            if lower == "/reiniciar":
                # iniciar_asistente.bat vuelve a abrir el asistente al recibir el código 3.
                console.print("[cyan]Reiniciando para cargar los cambios...[/cyan]")
                motor_tareas.detener()
                avatar.detener()
                sys.exit(CODIGO_REINICIO)
            if lower.startswith("/auditoria"):
                from core import auditoria
                tabla = Table(title="Últimas acciones (data/auditoria/acciones.jsonl)")
                for columna in ("hora", "origen", "tipo", "acción", "detalle", "resultado"):
                    tabla.add_column(columna, overflow="fold")
                for a in auditoria.recientes(int(prompt.partition(" ")[2] or 20)):
                    tabla.add_row(a["fecha"][11:19], a["origen"], a["tipo"], a["nombre"][:40],
                                  a["detalle"][:60], ("✓ " if a["ok"] else "✗ ") + a["resultado"][:60])
                console.print(tabla)
                continue
            if lower.startswith("/olvidar"):
                from memory import perfil
                objetivo = prompt.partition(" ")[2].strip()
                console.print(f"Olvidé {perfil.olvidar(objetivo)} dato(s)." if objetivo else "Uso: /olvidar <id o texto>")
                continue
            responder(prompt)
        except (KeyboardInterrupt, EOFError):
            break
    motor_tareas.detener()
    avatar.detener()
    console.print("[dim]Cerrando asistente.[/dim]")


if __name__ == "__main__":
    main()
