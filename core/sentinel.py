"""Centinela no bloqueante para RAM, GPU y puertos TCP nuevos."""
from __future__ import annotations

import shutil
import subprocess
import threading
import time

import psutil
from rich.console import Console


class Sentinel:
    def __init__(self, interval: int = 40, voice_enabled=None) -> None:
        self.interval = interval
        self.running = False
        self.thread: threading.Thread | None = None
        self.initial_ports = self._listen_ports()
        self.last_alert: dict[str, float] = {}
        self.console = Console()
        self.voice_enabled = voice_enabled or (lambda: False)

    @staticmethod
    def _listen_ports() -> set[int]:
        try:
            return {c.laddr.port for c in psutil.net_connections(kind="tcp") if c.status == psutil.CONN_LISTEN and c.laddr}
        except (OSError, psutil.AccessDenied):
            return set()

    def _alert(self, kind: str, text: str) -> None:
        now = time.monotonic()
        if now - self.last_alert.get(kind, -10**9) < 300:
            return
        self.last_alert[kind] = now
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
            out = subprocess.run([executable, "--query-gpu=temperature.gpu,memory.used", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=3, check=True).stdout.strip()
            temp, memory = [float(value.strip()) for value in out.split(",", 1)]
            return temp, memory
        except (OSError, ValueError, subprocess.SubprocessError):
            return 0.0, 0.0

    def check_once(self) -> None:
        if psutil.virtual_memory().percent > 90:
            self._alert("ram", f"RAM por encima del 90% ({psutil.virtual_memory().percent:.0f}%).")
        temp, memory = self._gpu()
        if temp > 82:
            self._alert("gpu_temp", f"GPU a {temp:.0f}°C.")
        if memory > 3950:
            self._alert("vram", f"VRAM usada: {memory:.0f} MB.")
        new_ports = self._listen_ports() - self.initial_ports
        if new_ports:
            self._alert("ports", f"Nuevos puertos TCP LISTEN: {sorted(new_ports)}.")

    def _run(self) -> None:
        while self.running:
            self.check_once()
            time.sleep(self.interval)

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._run, name="asistente-centinela", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.running = False
