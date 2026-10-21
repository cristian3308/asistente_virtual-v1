"""Centinela: vigila el PC y avisa solo de lo que importa, como JARVIS.

- Puertos nuevos con contexto: qué programa los abrió (nombre, PID, ruta) y si quedan
  expuestos a toda tu red (0.0.0.0) o solo a este PC. Gravedad:
    bajo  → solo este PC (normal al programar): no molesta.
    medio → expuesto a la red: aviso en consola, voz y celular.
    alto  → expuesto y el programa está en Descargas o Temp: además por Telegram.
  Los servicios propios del asistente (web, avatar, Hindsight, Ollama) no cuentan.
- RAM, temperatura y VRAM de la GPU, batería baja y disco casi lleno.
- Errores copiados al portapapeles (Traceback, Exception…): ofrece revisarlos.
Cada tipo de aviso se repite como mucho cada 5 minutos.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass

import psutil
from rich.console import Console

from config import settings

INTERVALO = 15
_RUTAS_SOSPECHOSAS = re.compile(r"\\(?:appdata\\local\\temp|temp|downloads|descargas)\\", re.IGNORECASE)
_ERROR_COPIADO = re.compile(
    r"Traceback \(most recent call last\)|\b\w+(?:Error|Exception)\b:|npm ERR!|error CS\d{4}|"
    r"FATAL|Segmentation fault|Unhandled exception|SyntaxError", re.IGNORECASE)
_PROCESOS_PROPIOS = {"ollama.exe", "ollama app.exe", "ollama_llama_server.exe"}


@dataclass(frozen=True)
class PuertoAbierto:
    puerto: int
    ip: str
    pid: int
    proceso: str
    ruta: str

    @property
    def expuesto(self) -> bool:
        return self.ip in ("0.0.0.0", "::", "")

    @property
    def de_windows(self) -> bool:
        """Servicios del propio Windows: abren y cierran puertos todo el tiempo."""
        return self.pid == 4 or self.proceso == "System" or self.ruta.lower().startswith(
            os.environ.get("SystemRoot", r"C:\Windows").lower() + "\\")

    def gravedad(self) -> str:
        if not self.expuesto or self.de_windows:
            return "bajo"
        return "alto" if _RUTAS_SOSPECHOSAS.search(self.ruta + "\\") else "medio"

    def describir(self) -> str:
        donde = "expuesto a toda tu red" if self.expuesto else "solo accesible desde este PC"
        programa = f"{self.proceso} (PID {self.pid})" if self.pid else "un programa que no pude identificar"
        ruta = f" — {self.ruta}" if self.ruta else ""
        return f"{programa} abrió el puerto {self.puerto}, {donde}{ruta}"


def puertos_abiertos() -> dict[tuple[str, int], PuertoAbierto]:
    """Puertos TCP en escucha con el programa que los abrió (si Windows deja verlo)."""
    resultado = {}
    try:
        conexiones = psutil.net_connections(kind="tcp")
    except (OSError, psutil.AccessDenied):
        return resultado
    for c in conexiones:
        if c.status != psutil.CONN_LISTEN or not c.laddr:
            continue
        nombre, ruta = "", ""
        if c.pid:
            try:
                proceso = psutil.Process(c.pid)
                nombre = proceso.name()
                ruta = proceso.exe()
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                pass
        resultado[(c.laddr.ip, c.laddr.port)] = PuertoAbierto(c.laddr.port, c.laddr.ip, c.pid or 0, nombre, ruta)
    return resultado


def es_propio(p: PuertoAbierto) -> bool:
    """Servicios del propio asistente: no son una amenaza."""
    puertos = {settings.WEB_PORT, 8765, settings.HINDSIGHT_PUERTO, 11434}
    if p.puerto in puertos or p.proceso.lower() in _PROCESOS_PROPIOS:
        return True
    ruta = p.ruta.lower()
    raiz = str(settings.ROOT_DIR).lower()
    # .pg0 es la base de datos integrada de Hindsight.
    return bool(ruta) and (ruta.startswith(raiz) or ruta == sys.executable.lower() or p.pid == os.getpid()
                           or "\\.pg0\\" in ruta)


def informe_exposicion() -> str:
    """Programas que hoy aceptan conexiones desde toda tu red (sin contar Windows ni el asistente)."""
    vistos = {}
    for p in puertos_abiertos().values():
        if p.expuesto and not p.de_windows and not es_propio(p):
            vistos.setdefault((p.proceso or "desconocido", p.ruta), set()).add(p.puerto)
    if not vistos:
        return "Ningún programa (aparte de Windows) acepta conexiones desde tu red. Todo en orden."
    lineas = [f"- {nombre} → puerto(s) {', '.join(map(str, sorted(puertos)))}" + (f"  ({ruta})" if ruta else "")
              for (nombre, ruta), puertos in sorted(vistos.items())]
    return ("Estos programas aceptan conexiones desde cualquier equipo de tu red (no solo este PC):\n"
            + "\n".join(lineas) + "\nSi alguno no lo usas, conviene cerrarlo o limitarlo a este PC.")


def error_copiado(texto: str) -> str | None:
    """Si el portapapeles parece un error, devuelve una etiqueta corta del tipo de error."""
    if not texto or len(texto) > 20000 or not _ERROR_COPIADO.search(texto):
        return None
    if "Traceback" in texto:
        return "de Python"
    if "npm ERR!" in texto:
        return "de npm"
    tipo = re.search(r"\b(\w+(?:Error|Exception))\b", texto)
    return f"({tipo.group(1)})" if tipo else ""


class Sentinel:
    def __init__(self, interval: int = INTERVALO, voice_enabled=None, avisar=None) -> None:
        self.interval = interval
        self.running = False
        self.thread: threading.Thread | None = None
        self.conocidos = set(puertos_abiertos())
        self.last_alert: dict[str, float] = {}
        self.console = Console()
        self.voice_enabled = voice_enabled or (lambda: False)
        self.avisar = avisar          # avisar(texto, gravedad); si falta, consola y voz
        self._portapapeles = None

    # Compatibilidad con la versión anterior y con las pruebas.
    @staticmethod
    def _listen_ports() -> set[int]:
        return {puerto for (_ip, puerto) in puertos_abiertos()}

    def _alert(self, kind: str, text: str, gravedad: str = "medio", cada: float = 300) -> None:
        now = time.monotonic()
        if now - self.last_alert.get(kind, -10**9) < cada:
            return
        self.last_alert[kind] = now
        if self.avisar is not None:
            self.avisar(text, gravedad)
            return
        self.console.print(f"[bold yellow]⚠ Centinela:[/bold yellow] {text}")
        if self.voice_enabled():
            try:
                from voice.mouth_tts import hablar
                hablar(text)
            except Exception:
                pass

    def _gpu(self) -> tuple[float, float]:
        executable = shutil.which("nvidia-smi.exe") or shutil.which("nvidia-smi")
        if not executable:
            return 0.0, 0.0
        try:
            out = subprocess.run([executable, "--query-gpu=temperature.gpu,memory.used", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=3, check=True,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip()
            temp, memory = [float(value.strip()) for value in out.split(",", 1)]
            return temp, memory
        except (OSError, ValueError, subprocess.SubprocessError):
            return 0.0, 0.0

    def revisar_puertos(self) -> list[PuertoAbierto]:
        actuales = puertos_abiertos()
        nuevos = [p for clave, p in actuales.items() if clave not in self.conocidos and not es_propio(p)]
        self.conocidos = set(actuales)
        for p in nuevos:
            gravedad = p.gravedad()
            if gravedad == "bajo":
                continue
            prefijo = "Atención, señor: " if gravedad == "alto" else "Aviso: "
            sugerencia = (" Está en una carpeta poco habitual para un servidor. Si no lo reconoces, puedo cerrarlo "
                          f"(dime 'cierra el proceso {p.pid}')." if gravedad == "alto"
                          else " Si no es tuyo, dime y lo cierro.")
            self._alert(f"puerto-{p.puerto}", prefijo + p.describir() + "." + sugerencia, gravedad)
        return nuevos

    def revisar_portapapeles(self) -> str | None:
        try:
            import pyperclip
            texto = pyperclip.paste()
        except Exception:
            return None
        if texto == self._portapapeles:
            return None
        self._portapapeles = texto
        tipo = error_copiado(texto)
        if tipo is None:
            return None
        self._alert("portapapeles", f"Copiaste un error {tipo}. Si quieres, dime 'revisa el error que copié' y te digo qué pasa.".replace("  ", " "),
                    "info", cada=60)
        return tipo

    def check_once(self) -> None:
        memoria = psutil.virtual_memory().percent
        if memoria > 90:
            self._alert("ram", f"La RAM está al {memoria:.0f} %. Conviene cerrar algo.")
        temp, memory = self._gpu()
        if temp > 82:
            self._alert("gpu_temp", f"La GPU está a {temp:.0f} °C. Algo la está exigiendo mucho.")
        if memory > 3950:
            self._alert("vram", f"La memoria de la GPU está casi llena ({memory:.0f} MB).")
        try:
            bateria = psutil.sensors_battery()
        except Exception:
            bateria = None
        if bateria is not None and not bateria.power_plugged and bateria.percent <= 20:
            self._alert("bateria", f"Batería al {bateria.percent:.0f} %, señor. Sería buen momento para conectarlo.",
                        "medio", cada=600)
        try:
            disco = psutil.disk_usage(os.environ.get("SystemDrive", "C:") + "\\")
            if disco.percent >= 92:
                self._alert("disco", f"El disco está al {disco.percent:.0f} % ({disco.free / 2**30:.1f} GB libres).",
                            "medio", cada=3600)
        except Exception:
            pass
        self.revisar_puertos()
        self.revisar_portapapeles()

    def _run(self) -> None:
        while self.running:
            try:
                self.check_once()
            except Exception:
                pass
            time.sleep(self.interval)

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._run, name="asistente-centinela", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.running = False
