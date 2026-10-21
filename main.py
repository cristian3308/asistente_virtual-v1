"""Interfaz interactiva de consola del asistente."""
from __future__ import annotations

import json
import os
import sys

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")   # sin el saludo de pygame en la consola
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
    def aviso_centinela(texto: str, gravedad: str) -> None:
        """Avisos del centinela: consola y celular siempre; voz si no está hablando contigo; Telegram si es grave."""
        from core import eventos
        colores = {"alto": "bold red", "medio": "bold yellow"}
        console.print(f"\n[{colores.get(gravedad, 'cyan')}]🛡️ {texto}[/{colores.get(gravedad, 'cyan')}]")
        eventos.publicar("aviso", texto, origen="consola", ok=gravedad not in {"alto", "medio"}, gravedad=gravedad)
        if gravedad == "alto":
            from interfaces import notificaciones
            notificaciones.enviar_telegram("🛡️ " + texto)
        if gravedad in {"alto", "medio"}:
            from interfaces import push
            push.enviar_en_segundo_plano("🛡️ " + texto, "Jarvis · seguridad")
        if gravedad in {"alto", "medio"} and not atendiendo_voz():
            def decir() -> None:
                try:
                    from voice.mouth_tts import hablar
                    hablar(texto)
                except Exception:
                    pass
            threading.Thread(target=decir, name="centinela-voz", daemon=True).start()

    atendiendo_voz = lambda: False   # se reemplaza al crear el despertador
    sentinel = Sentinel(voice_enabled=lambda: voice_enabled, avisar=lambda t, g: aviso_centinela(t, g))
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
    from core import presencia

    ultimo_saludo = [0.0]

    def al_volver(texto: str) -> None:
        """Te recibe cuando vuelves al PC: en la consola, en la app del celular y con voz."""
        import time as _time
        from core import estado, eventos
        if _time.monotonic() - ultimo_saludo[0] < 300:
            return   # ya te saludó el teclado o la cámara hace un momento
        ultimo_saludo[0] = _time.monotonic()
        console.print(f"\n[bold cyan]🤖 {texto}[/bold cyan]")
        eventos.publicar("aviso", texto, origen="consola")
        estado.publicar("happy", duracion=3.0, detalle="¡Bienvenido!")
        try:
            from voice.mouth_tts import hablar
            hablar(texto)
        except Exception:
            pass

    vigia_presencia = presencia.Presencia(al_volver)
    if settings.SALUDO_AL_VOLVER:
        vigia_presencia.iniciar()

    # --- "Jarvis": activación por voz, interrupción y seguimiento de la conversación ---
    from voice import despertar
    turno_voz = threading.Lock()
    atendiendo = threading.Event()
    SALIR_VOZ = {"salir", "terminar", "adiós", "adios", "gracias jarvis", "eso es todo", "nada"}

    def escuchar_orden(espera: float) -> str:
        from voice.ear_stt import escuchar
        despertador.pausar(True)
        try:
            return escuchar(espera_inicio=espera)
        finally:
            despertador.pausar(False)

    def atender_llamada(orden: str) -> None:
        """Un turno por voz: si solo dijiste "Jarvis", te escucha; luego responde y espera tu siguiente frase."""
        from voice import efectos
        from voice.mouth_tts import SentenceSpeaker, interrumpido
        if not turno_voz.acquire(timeout=30):
            return
        atendiendo.set()
        try:
            if not orden:
                efectos.sonido("escucha")
                orden = escuchar_orden(settings.VOZ_ESPERA_INICIO)
                if not orden:
                    return
                efectos.sonido("listo")
            while orden:
                from core import entender
                orden = entender.normalizar(orden)
                console.print(f"\n[green]🎙️ Tú (voz):[/green] {orden}")
                if orden.lower().strip(" .,!¡¿?") in SALIR_VOZ:
                    efectos.sonido("listo")
                    return
                hablante = SentenceSpeaker(frase_de_espera=efectos.frase_de_espera)
                try:
                    answer, motor = brain.ask(orden, on_token=hablante.feed)
                finally:
                    hablante.close()   # espera a que termine de hablar (o a que lo calles)
                console.print(Markdown(answer))
                console.print(f"[dim]Motor: {motor} · di algo más o espera {settings.SEGUIMIENTO_SEGUNDOS:g} s[/dim]")
                if interrumpido():
                    return   # lo llamaste otra vez: esa nueva orden se atiende enseguida
                orden = escuchar_orden(settings.SEGUIMIENTO_SEGUNDOS)
                if orden:
                    efectos.sonido("listo")
        except Exception as exc:
            console.print(f"[red]Error en el turno por voz: {exc}[/red]")
        finally:
            atendiendo.clear()
            turno_voz.release()

    despertador = despertar.Despertador(atender_llamada, ocupado=atendiendo.is_set)
    atendiendo_voz = atendiendo.is_set

    # --- Cámara: reconocerte, ver tu ánimo y avisar si hay alguien que no conoce ---
    from core import camara
    camara_estado = {"fuera_desde": None, "aviso_desconocido": 0.0}

    def al_cambiar_camara(evento: str, datos: dict) -> None:
        import time as _time
        from datetime import datetime, timedelta
        from core import eventos
        if evento == "te_fuiste":
            camara_estado["fuera_desde"] = datetime.now()
        elif evento == "llegaste":
            desde = camara_estado["fuera_desde"]
            camara_estado["fuera_desde"] = None
            if desde and datetime.now() - desde >= timedelta(minutes=settings.SALUDO_TRAS_MINUTOS):
                al_volver(presencia.resumen_de_regreso(desde))
        elif evento == "desconocido" and _time.monotonic() - camara_estado["aviso_desconocido"] > 600:
            camara_estado["aviso_desconocido"] = _time.monotonic()
            texto = f"⚠️ Hay alguien frente a tu PC que no reconozco ({datos.get('desconocidos', 1)} persona(s)) y tú no estás."
            eventos.publicar("aviso", texto, origen="consola", ok=False)
            console.print(f"[bold red]{texto}[/bold red]")
            from interfaces import notificaciones, push
            notificaciones.enviar_telegram(texto)
            push.enviar_en_segundo_plano(texto, "Jarvis · seguridad")

    camara_jarvis = camara.obtener(al_cambiar_camara)
    from memory import hindsight_memoria
    console.print(f"[dim]{hindsight_memoria.iniciar()}[/dim]")
    if settings.WEB:
        from interfaces import web_app
        console.print(f"[dim]{web_app.iniciar(brain)}[/dim]")
    console.print(Panel.fit(
        "Asistente Híbrido — Windows · RTX 3050 · OpenCode Go / Ollama\n"
        f"Ollama: {'activo' if settings.ollama_activo() else 'apagado'} | Cloud: {'configurado' if settings.cloud_configurado() else 'sin API key'}\n"
        "Comandos: /estado /limpiar /indexar <ruta> /recuerdos /habilidades /cargar_habilidades /ver <pregunta> /centinela <on|off> /benchmark /modelo <codigo|razonamiento|rapido|local|turbo> /tareas /tarea <objetivo> /cancelar /pausar /reactivar /programar <cambio> /revisar /aprobar /rechazar /deshacer /olvidar /auditoria /fallos /procedimientos /reiniciar /web /jarvis <on|off> /camara <on|off|registrar|olvidar> /parar /reanudar /voz /voces /voz_probar /voz_usar /conversar /avatar /salir",
        title="🤖 Asistente Virtual Profundo", border_style="cyan",
    ))
    if settings.CENTINELA:
        sentinel.start()
    if settings.PALABRA_ACTIVACION:
        from voice import efectos
        efectos.precargar_frases()
        console.print(f"[green]🎙️ {despertador.iniciar()}[/green]")

    def responder(prompt: str) -> None:
        """Genera una respuesta y, si corresponde, la reproduce completa."""
        visible = []
        speaker = None
        if voice_enabled:
            try:
                from voice.mouth_tts import SentenceSpeaker
                from voice import efectos
                speaker = SentenceSpeaker(frase_de_espera=efectos.frase_de_espera)
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
            from voice import efectos
            precargar()
            efectos.precargar_frases()
            console.print(f"[green]Conversación activa. Habla; respondo cuando te calles "
                          f"{settings.VOZ_SILENCIO_FIN:g} s. Di 'salir' para terminar.[/green]")
            while True:
                console.print("[dim]Escuchando...[/dim]")
                efectos.sonido("escucha")
                prompt = escuchar()
                if not prompt:
                    continue
                efectos.sonido("listo")
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
                        from voice import efectos
                        console.print("[dim]Escuchando... (termino cuando dejes de hablar)[/dim]")
                        efectos.sonido("escucha")
                        prompt = escuchar()
                        efectos.sonido("listo")
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
                from voice import efectos
                efectos.precargar_frases()   # graba "Enseguida." y compañía con la voz nueva
                continue
            if lower == "/voz":
                voice_enabled = not voice_enabled
                if voice_enabled:
                    from voice.ear_stt import precargar
                    from voice import efectos
                    precargar()
                    efectos.precargar_frases()
                console.print(f"Voz {'activada: pulsa Enter para grabar y escribe /voz para desactivar.' if voice_enabled else 'desactivada.'}")
                continue
            if lower.startswith("/camara") or lower.startswith("/cámara"):
                accion = lower.partition(" ")[2].strip() or "estado"
                if accion == "on":
                    console.print(camara_jarvis.encender())
                elif accion == "off":
                    console.print(camara_jarvis.apagar())
                elif accion == "registrar":
                    console.print("Mírame a la cámara unos segundos, con buena luz y solo tú en la imagen...")
                    console.print(camara_jarvis.registrar())
                elif accion == "olvidar":
                    console.print(camara_jarvis.olvidar())
                else:
                    datos = camara_jarvis.ultimo
                    console.print(("Encendida. " + (camara_jarvis.resumen() or "Aún sin datos.")) if camara_jarvis.encendida()
                                  else "Apagada. /camara on para encenderla · /camara registrar para que te reconozca.")
                continue
            if lower.startswith("/jarvis"):
                if lower.endswith("off"):
                    despertador.detener()
                    console.print("Ya no escucho \"Jarvis\". Actívalo con /jarvis on.")
                else:
                    from voice import efectos
                    efectos.precargar_frases()
                    console.print(f"[green]🎙️ {despertador.iniciar()}[/green]")
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
                elif action in {"informe", "reporte", "red"}:
                    from core.sentinel import informe_exposicion
                    console.print(Panel(informe_exposicion(), title="🛡️ Exposición en tu red", border_style="yellow"))
                else:
                    console.print("Uso: /centinela on|off|informe")
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
                from core import cambios
                comando, _, id_tarea = prompt.partition(" ")
                comando = comando.lower()
                try:
                    info = cambios.revisar(id_tarea)
                    tarea, extra = info["tarea"], info["datos"]
                    if comando == "/aprobar" and info["puede_empezar"]:
                        console.print(cambios.autorizar_inicio(tarea["id"]))
                    elif comando == "/revisar":
                        console.print(Panel(tarea["resultado"] or "", title=f"Cambio {tarea['id']}: {tarea['objetivo'][:60]}",
                                            border_style="cyan"))
                        console.print(Syntax(info["diff"] or "(sin cambios)", "diff", line_numbers=False, word_wrap=True))
                        if info["avisos"]:
                            console.print(Panel("\n".join(info["avisos"][:30]), title="⚠ Revisa con cuidado: toca seguridad, comandos o secretos",
                                                border_style="red"))
                        console.print(f"[dim]/aprobar {tarea['id']} para aplicarlo · /rechazar {tarea['id']} para descartarlo[/dim]")
                    elif comando == "/aprobar":
                        if not info["puede_aplicar"]:
                            console.print("Ese cambio no está esperando revisión.")
                            continue
                        forzar = not extra.get("pruebas_ok")
                        if forzar and not confirmar_consola("⚠ Las pruebas FALLAN con este cambio. ¿Aplicarlo de todos modos?"):
                            console.print("No se aplicó.")
                        elif confirmar_consola(f"¿Aplicar a tu código los cambios en {', '.join(extra.get('archivos', []))}?"):
                            merge = cambios.aplicar(tarea["id"], aceptar_pruebas_fallidas=forzar)
                            console.print(f"[green]Aplicado (commit {merge[:7]}). Escribe /reiniciar para usarlo ya. "
                                          f"Si algo va mal: /deshacer {tarea['id']}[/green]")
                    elif comando == "/rechazar":
                        cambios.rechazar(tarea["id"])
                        console.print(f"Cambio {tarea['id']} descartado; tu código no se tocó.")
                    elif comando == "/deshacer":
                        revert = cambios.deshacer(tarea["id"])
                        console.print(f"[green]Cambio deshecho (commit {revert[:7]}). Reinicia el asistente.[/green]")
                except cambios.CambioInvalido as exc:
                    console.print(f"[yellow]{exc} Míralos con /tareas.[/yellow]")
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
            if lower == "/web":
                from interfaces import web_app
                console.print(Panel(
                    f"En este PC: {web_app.direccion()}\n"
                    f"Token (no lo compartas): [bold]{web_app.token()}[/bold]\n\n"
                    "En el celular, con Tailscale en ambos y este comando una sola vez en el PC:\n"
                    f"  tailscale serve --bg {settings.WEB_PORT}\n"
                    "luego abre en el celular la dirección https://<nombre-del-pc>.<tu-red>.ts.net que muestra "
                    "`tailscale serve status`, entra con el token y en el menú de Chrome elige «Instalar app».",
                    title="📱 App en el celular", border_style="cyan"))
                continue
            if lower == "/reiniciar":
                # iniciar_asistente.bat vuelve a abrir el asistente al recibir el código 3.
                console.print("[cyan]Reiniciando para cargar los cambios...[/cyan]")
                motor_tareas.detener()
                vigia_presencia.detener()
                despertador.detener()
                camara_jarvis.apagar()
                hindsight_memoria.detener()
                avatar.detener()
                if settings.WEB:
                    from interfaces import web_app
                    web_app.detener()
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
    vigia_presencia.detener()
    despertador.detener()
    camara_jarvis.apagar()
    hindsight_memoria.detener()
    avatar.detener()
    if settings.WEB:
        from interfaces import web_app
        web_app.detener()
    console.print("[dim]Cerrando asistente.[/dim]")


if __name__ == "__main__":
    main()
