"""Avatar animado: servidor local del estado y ventana flotante con robot-heads.

El servidor escucha solo en 127.0.0.1 y sirve la app compilada de `avatar/dist`
más `/estado`. La ventana (pywebview) corre en un proceso aparte porque exige el
hilo principal, que ya ocupa la consola.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from config import settings
from core import estado

DIST_DIR = settings.ROOT_DIR / "avatar" / "dist"
ELECTRON_EXE = settings.ROOT_DIR / "avatar" / "node_modules" / "electron" / "dist" / "electron.exe"
ELECTRON_MAIN = settings.ROOT_DIR / "avatar" / "electron" / "main.cjs"

_server: ThreadingHTTPServer | None = None
_window: subprocess.Popen | None = None


class _Handler(SimpleHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 (nombre impuesto por http.server)
        if self.path.split("?", 1)[0] == "/estado":
            body = json.dumps(estado.actual(), ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def log_message(self, *_args) -> None:
        # El sondeo cada 120 ms llenaría la consola.
        return


class _Servidor(ThreadingHTTPServer):
    # En Windows SO_REUSEADDR deja que dos procesos escuchen en el mismo puerto y
    # se roben las peticiones; sin él, un puerto ocupado falla y se elige otro.
    allow_reuse_address = False


def disponible() -> tuple[bool, str]:
    if not (DIST_DIR / "index.html").is_file():
        return False, "Falta compilar el avatar: en la carpeta avatar ejecuta `npm install` y `npm run build`."
    if ELECTRON_EXE.is_file():
        return True, ""
    try:
        import webview  # noqa: F401
    except ImportError:
        return False, "Falta Electron (`npm install` en la carpeta avatar) o pywebview."
    return True, ""


def _comando_ventana(url: str) -> list[str]:
    # Electron da transparencia real y no frena la animación sin foco; el control
    # WebView2 de WinForms (pywebview) no admite fondo transparente en Windows.
    if ELECTRON_EXE.is_file():
        # --padre: el robot se cierra solo si este proceso muere (p. ej. al cerrar la consola con la X).
        return [str(ELECTRON_EXE), str(ELECTRON_MAIN), url, f"--padre={os.getpid()}"]
    return [sys.executable, "-m", "interfaces.avatar_window", url]


def _iniciar_servidor() -> str:
    global _server
    if _server is None:
        handler = partial(_Handler, directory=str(DIST_DIR))
        # Puerto 0 si el 8765 está ocupado: el sistema elige uno libre.
        try:
            _server = _Servidor(("127.0.0.1", 8765), handler)
        except OSError:
            _server = _Servidor(("127.0.0.1", 0), handler)
        threading.Thread(target=_server.serve_forever, name="avatar-http", daemon=True).start()
    return f"http://127.0.0.1:{_server.server_address[1]}/"


def iniciar() -> str:
    """Abre la ventana flotante del avatar; devuelve un mensaje para la consola."""
    global _window
    ok, motivo = disponible()
    if not ok:
        return motivo
    url = _iniciar_servidor()
    if _window is None or _window.poll() is not None:
        _window = subprocess.Popen(_comando_ventana(url), cwd=str(settings.ROOT_DIR),
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return f"Avatar abierto ({url})."


def detener() -> str:
    global _window
    if _window is not None and _window.poll() is None:
        # Electron abre procesos hijos (GPU, render): se cierra todo el árbol.
        subprocess.run(["taskkill", "/PID", str(_window.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    _window = None
    return "Avatar cerrado."


def abierto() -> bool:
    return _window is not None and _window.poll() is None
