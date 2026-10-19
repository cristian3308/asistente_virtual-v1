"""App web/PWA para usar el asistente desde el celular.

Seguridad:
- Escucha en 127.0.0.1 por defecto. Para el celular se recomienda `tailscale serve`,
  que da HTTPS privado entre tus dispositivos sin abrir puertos.
- Toda la API exige el token (cabecera Authorization: Bearer). Tras varios intentos
  fallidos se bloquea un rato para todos (es una app de un solo usuario).
- Igual que Telegram: no pide confirmaciones interactivas, así que lo que necesita
  confirmación (PowerShell, instalar habilidades…) se rechaza desde aquí. Todo queda
  auditado con origen "web".
"""
# Sin `from __future__ import annotations`: FastAPI necesita las anotaciones reales
# (Request, modelos) de las funciones definidas dentro de crear_app.
import hmac
import json
import queue
import secrets
import shutil
import tempfile
import threading
import time
from pathlib import Path

from config import settings

ESTATICOS = Path(__file__).resolve().parent / "web"
ARCHIVO_TOKEN = settings.DATA_DIR / "web_token.txt"
MAX_FALLOS = 8
BLOQUEO_SEGUNDOS = 15 * 60
MAX_AUDIO = 10 * 1024 * 1024

_servidor = None


def token() -> str:
    """Token de acceso: el de .env o uno aleatorio guardado en data/web_token.txt."""
    if len(settings.WEB_TOKEN) >= 16:
        return settings.WEB_TOKEN
    if ARCHIVO_TOKEN.exists():
        guardado = ARCHIVO_TOKEN.read_text(encoding="utf-8").strip()
        if len(guardado) >= 16:
            return guardado
    ARCHIVO_TOKEN.parent.mkdir(parents=True, exist_ok=True)
    nuevo = secrets.token_urlsafe(18)
    ARCHIVO_TOKEN.write_text(nuevo, encoding="utf-8")
    return nuevo


class _Cerradura:
    """Cuenta intentos fallidos y bloquea el acceso un tiempo al pasar el límite."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._fallos: list[float] = []
        self._hasta = 0.0

    def bloqueada(self) -> bool:
        return time.monotonic() < self._hasta

    def fallo(self) -> None:
        ahora = time.monotonic()
        with self._lock:
            self._fallos = [f for f in self._fallos if ahora - f < BLOQUEO_SEGUNDOS] + [ahora]
            if len(self._fallos) >= MAX_FALLOS:
                self._hasta = ahora + BLOQUEO_SEGUNDOS
                self._fallos.clear()


def crear_app(brain, clave: str | None = None):
    from fastapi import Depends, FastAPI, HTTPException, Request
    from fastapi.concurrency import run_in_threadpool
    from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel, Field

    from core import auditoria, cambios, estado, tareas
    from core.self_coder import confirmation_context, reset_confirmation_context
    from memory import perfil

    clave = clave or token()
    cerradura = _Cerradura()
    app = FastAPI(title="Asistente", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def cabeceras(request: Request, call_next):
        respuesta = await call_next(request)
        respuesta.headers.update({
            "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; media-src 'self' blob:; "
                                       "frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Cache-Control": respuesta.headers.get("Cache-Control", "no-store"),
        })
        return respuesta

    def autorizado(request: Request) -> None:
        if cerradura.bloqueada():
            raise HTTPException(429, "Demasiados intentos fallidos. Espera unos minutos.")
        dado = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        if not hmac.compare_digest(dado.encode(), clave.encode()):
            cerradura.fallo()
            auditoria.registrar("web", "acceso denegado", request.client.host if request.client else "?", ok=False)
            raise HTTPException(401, "Token incorrecto.")

    api = [Depends(autorizado)]

    def _web(funcion, *args, **kwargs):
        """Ejecuta como canal web: auditado como 'web' y sin confirmaciones interactivas."""
        tok_origen = auditoria.origen("web")
        tok_conf = confirmation_context(False)
        try:
            return funcion(*args, **kwargs)
        finally:
            reset_confirmation_context(tok_conf)
            auditoria.restaurar_origen(tok_origen)

    class Mensaje(BaseModel):
        texto: str = Field(min_length=1, max_length=8000)

    class NuevaTarea(BaseModel):
        objetivo: str = Field(min_length=3, max_length=2000)

    class Aplicar(BaseModel):
        aceptar_pruebas_fallidas: bool = False

    @app.exception_handler(cambios.CambioInvalido)
    async def cambio_invalido(_request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    # ---------- páginas (sin token: no contienen datos) ----------
    @app.get("/", include_in_schema=False)
    def inicio():
        return FileResponse(ESTATICOS / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/sw.js", include_in_schema=False)
    def service_worker():
        return FileResponse(ESTATICOS / "sw.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})

    @app.get("/manifest.webmanifest", include_in_schema=False)
    def manifiesto():
        return FileResponse(ESTATICOS / "manifest.webmanifest", media_type="application/manifest+json")

    app.mount("/static", StaticFiles(directory=ESTATICOS), name="static")

    # ---------- API ----------
    @app.post("/api/login", dependencies=api)
    def login():
        auditoria.registrar("web", "inicio de sesión", ok=True)
        return {"ok": True, "usuario": settings.USER_NAME}

    @app.get("/api/estado", dependencies=api)
    def ver_estado():
        return {**estado.actual(), "detenido": auditoria.detenido(), "usuario": settings.USER_NAME,
                "ollama": settings.ollama_activo(), "nube": settings.cloud_configurado()}

    @app.post("/api/chat", dependencies=api)
    def chat(mensaje: Mensaje):
        if brain is None:
            raise HTTPException(503, "El cerebro del asistente no está disponible.")
        cola: queue.Queue = queue.Queue()

        def trabajar() -> None:
            try:
                respuesta, motor = _web(brain.ask, mensaje.texto, on_token=lambda t: cola.put({"t": t}))
                cola.put({"fin": respuesta, "motor": motor})
            except Exception as exc:
                cola.put({"error": f"{type(exc).__name__}: {exc}"})
            finally:
                cola.put(None)

        threading.Thread(target=trabajar, name="asistente-web-chat", daemon=True).start()

        def lineas():
            while (item := cola.get()) is not None:
                yield json.dumps(item, ensure_ascii=False) + "\n"

        return StreamingResponse(lineas(), media_type="application/x-ndjson")

    @app.post("/api/voz", dependencies=api)
    async def voz(request: Request):
        """Nota de voz grabada en el celular → texto (luego la app la envía al chat)."""
        audio = await request.body()
        if not audio:
            raise HTTPException(400, "No llegó audio.")
        if len(audio) > MAX_AUDIO:
            raise HTTPException(413, "La nota de voz es demasiado larga.")
        tipo = request.headers.get("content-type", "")
        extension = ".ogg" if "ogg" in tipo else ".mp4" if "mp4" in tipo or "aac" in tipo else ".webm"
        carpeta = Path(tempfile.mkdtemp(prefix="asistente_web_voz_"))
        try:
            archivo = carpeta / f"nota{extension}"
            archivo.write_bytes(audio)
            from voice.ear_stt import transcribir_archivo
            texto = await run_in_threadpool(transcribir_archivo, archivo)
        finally:
            shutil.rmtree(carpeta, ignore_errors=True)   # el audio no se guarda
        return {"texto": texto}

    @app.post("/api/parar", dependencies=api)
    def parar():
        return {"mensaje": _web(auditoria.detener, "web")}

    @app.post("/api/reanudar", dependencies=api)
    def reanudar():
        return {"mensaje": _web(auditoria.reanudar)}

    @app.get("/api/tareas", dependencies=api)
    def ver_tareas(todas: bool = False):
        return [{**t, "datos": tareas.datos(t), "acciones": json.loads(t.get("acciones") or "[]")[-8:]}
                for t in tareas.listar(incluir_terminadas=todas, limite=60)]

    @app.post("/api/tareas", dependencies=api)
    def nueva_tarea(nueva: NuevaTarea):
        id_tarea = _web(tareas.crear, "agente", nueva.objetivo, origen="web")
        return {"id": id_tarea, "mensaje": f"Tarea [{id_tarea}] en cola. Te aviso al terminar."}

    @app.post("/api/tareas/{id_tarea}/{accion}", dependencies=api)
    def accion_tarea(id_tarea: str, accion: str):
        funciones = {"cancelar": tareas.cancelar, "pausar": tareas.pausar, "reactivar": tareas.continuar}
        if accion not in funciones:
            raise HTTPException(404, "Acción desconocida.")
        if not _web(funciones[accion], id_tarea):
            raise HTTPException(409, f"No se pudo {accion} esa tarea en su estado actual.")
        return {"ok": True}

    @app.get("/api/cambios", dependencies=api)
    def ver_cambios(todos: bool = False):
        return [{**t, "datos": tareas.datos(t)} for t in cambios.listar(todos)]

    @app.get("/api/cambios/{id_tarea}", dependencies=api)
    def revisar_cambio(id_tarea: str):
        info = cambios.revisar(id_tarea)
        return {**info, "diff": info["diff"][:200_000]}

    @app.post("/api/cambios/{id_tarea}/empezar", dependencies=api)
    def empezar_cambio(id_tarea: str):
        return {"mensaje": _web(cambios.autorizar_inicio, id_tarea)}

    @app.post("/api/cambios/{id_tarea}/aplicar", dependencies=api)
    def aplicar_cambio(id_tarea: str, opciones: Aplicar):
        merge = _web(cambios.aplicar, id_tarea, opciones.aceptar_pruebas_fallidas)
        return {"merge": merge, "mensaje": f"Aplicado (commit {merge[:7]}). Reinicia el asistente para usarlo."}

    @app.post("/api/cambios/{id_tarea}/rechazar", dependencies=api)
    def rechazar_cambio(id_tarea: str):
        _web(cambios.rechazar, id_tarea)
        return {"mensaje": "Cambio descartado; tu código no se tocó."}

    @app.post("/api/cambios/{id_tarea}/deshacer", dependencies=api)
    def deshacer_cambio(id_tarea: str):
        revert = _web(cambios.deshacer, id_tarea)
        return {"mensaje": f"Cambio deshecho (commit {revert[:7]}). Reinicia el asistente."}

    @app.get("/api/memoria", dependencies=api)
    def memoria():
        return perfil.hechos()

    @app.delete("/api/memoria/{id_hecho}", dependencies=api)
    def olvidar(id_hecho: int):
        borrados = _web(perfil.olvidar, str(id_hecho))
        if not borrados:
            raise HTTPException(404, "Ese recuerdo no existe o ya estaba olvidado.")
        auditoria.registrar("memoria", "olvidar", id_hecho)
        return {"ok": True}

    @app.get("/api/actividad", dependencies=api)
    def actividad(limite: int = 60):
        return list(reversed(auditoria.recientes(max(1, min(limite, 300)))))

    return app


def iniciar(brain) -> str:
    """Arranca el servidor en un hilo. Devuelve un texto para la consola (sin el token)."""
    global _servidor
    if _servidor is not None:
        return direccion()
    try:
        import uvicorn
        app = crear_app(brain)
    except ImportError as exc:
        return f"App web no iniciada: falta {exc.name} (pip install -r requirements.txt)."
    if not puerto_libre():
        return (f"App web no iniciada: el puerto {settings.WEB_PORT} ya está en uso (¿otro asistente abierto?). "
                "Ciérralo o cambia ASSISTANT_WEB_PORT en .env.")
    _servidor = uvicorn.Server(uvicorn.Config(app, host=settings.WEB_HOST, port=settings.WEB_PORT,
                                              log_level="warning", access_log=False))

    def correr() -> None:
        try:
            _servidor.run()
        except SystemExit:   # puerto ocupado: uvicorn ya lo explicó en la consola
            pass

    threading.Thread(target=correr, name="asistente-web", daemon=True).start()
    return f"App web en {direccion()} · /web muestra cómo entrar desde el celular."


def puerto_libre() -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as prueba:
        try:
            prueba.bind((settings.WEB_HOST, settings.WEB_PORT))
        except OSError:
            return False
    return True


def direccion() -> str:
    return f"http://{'127.0.0.1' if settings.WEB_HOST in {'0.0.0.0', '::'} else settings.WEB_HOST}:{settings.WEB_PORT}"


def detener() -> None:
    if _servidor is not None:
        _servidor.should_exit = True
