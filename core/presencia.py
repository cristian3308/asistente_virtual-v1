"""Saber si estás frente al PC y recibirte cuando vuelves, como JARVIS.

Windows registra cuándo tocaste el teclado o el mouse por última vez (GetLastInputInfo);
leerlo no gasta nada. Si llevabas un rato fuera y vuelves, el asistente te saluda con un
resumen breve: tareas terminadas, cambios por revisar y el próximo recordatorio. El
resumen sale de los datos, sin modelo, así que es inmediato y no inventa nada.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta

from config import settings

REVISAR_CADA = 10.0   # segundos


def segundos_inactivo() -> float:
    """Segundos desde la última tecla o movimiento del mouse (0 si no se puede saber)."""
    try:
        import ctypes
        from ctypes import wintypes

        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(info)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0
        ahora = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF
        return ((ahora - info.dwTime) & 0xFFFFFFFF) / 1000.0
    except Exception:
        return 0.0


def _corto(texto: str, maximo: int = 50) -> str:
    texto = " ".join(texto.split())
    return texto if len(texto) <= maximo else texto[:maximo].rsplit(" ", 1)[0].rstrip(" ,.;:(") + "…"


def _saludo_por_hora(hora: int) -> str:
    return "Buenos días" if 5 <= hora < 12 else "Buenas tardes" if 12 <= hora < 19 else "Buenas noches"


def resumen_de_regreso(desde: datetime, ahora: datetime | None = None) -> str:
    """Lo importante que pasó mientras no estabas (sin modelo: solo datos reales)."""
    from core import tareas

    ahora = ahora or datetime.now()
    partes = [f"{_saludo_por_hora(ahora.hour)}, {settings.USER_NAME}. Bienvenido de vuelta."]
    todas = tareas.listar(incluir_terminadas=True, limite=200)
    desde_iso = desde.isoformat()
    terminadas = [t for t in todas if t["estado"] == "completada" and t["tipo"] != "recordatorio"
                  and (t["actualizada"] or "") >= desde_iso]
    fallidas = [t for t in todas if t["estado"] == "fallida" and (t["actualizada"] or "") >= desde_iso]
    por_revisar = [t for t in todas if t["tipo"] == "programa" and t["estado"] == "esperando_autorizacion"]
    limite = (ahora + timedelta(hours=3)).isoformat()
    proximos = sorted((t for t in todas if t["tipo"] == "recordatorio" and t["estado"] == "pendiente"
                       and t["programada_para"] and ahora.isoformat() <= t["programada_para"] <= limite),
                      key=lambda t: t["programada_para"])
    if terminadas:
        nombres = "; ".join(_corto(t["objetivo"]) for t in terminadas[:2])
        partes.append(f"Mientras no estabas terminé {len(terminadas)} tarea{'s' if len(terminadas) > 1 else ''}: {nombres}.")
    if fallidas:
        partes.append(f"{len(fallidas)} tarea{'s' if len(fallidas) > 1 else ''} no salió bien; la tienes en /tareas.")
    if por_revisar:
        partes.append(f"Hay {len(por_revisar)} cambio{'s' if len(por_revisar) > 1 else ''} de código esperando tu revisión.")
    if proximos:
        t = proximos[0]
        partes.append(f"Tu próximo recordatorio es a las {t['programada_para'][11:16]}: {_corto(t['objetivo'], 60)}.")
    if len(partes) == 1:
        partes.append("Todo tranquilo por aquí.")
    return " ".join(partes).replace("….", "…")


class Presencia:
    """Hilo que nota cuando vuelves tras `minutos` fuera y llama a `al_volver(texto)`."""

    def __init__(self, al_volver, minutos: float | None = None, medir=segundos_inactivo) -> None:
        self.al_volver = al_volver
        self.umbral = 60 * (settings.SALUDO_TRAS_MINUTOS if minutos is None else minutos)
        self.medir = medir
        self.fuera_desde: datetime | None = None
        self._parar = threading.Event()
        self._hilo: threading.Thread | None = None

    def revisar(self) -> str | None:
        """Una comprobación; devuelve el saludo si acabas de volver."""
        inactivo = self.medir()
        if inactivo >= self.umbral:
            if self.fuera_desde is None:
                self.fuera_desde = datetime.now() - timedelta(seconds=inactivo)
            return None
        if self.fuera_desde is not None and inactivo < REVISAR_CADA * 2:
            desde, self.fuera_desde = self.fuera_desde, None
            texto = resumen_de_regreso(desde)
            self.al_volver(texto)
            return texto
        return None

    def _bucle(self) -> None:
        while not self._parar.wait(REVISAR_CADA):
            try:
                self.revisar()
            except Exception:
                continue

    def iniciar(self) -> None:
        if self._hilo is None or not self._hilo.is_alive():
            self._parar.clear()
            self._hilo = threading.Thread(target=self._bucle, name="presencia", daemon=True)
            self._hilo.start()

    def detener(self) -> None:
        self._parar.set()
