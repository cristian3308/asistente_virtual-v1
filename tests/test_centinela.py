"""Centinela: avisa de lo que importa (puertos expuestos, batería, errores copiados) y nada más."""
from __future__ import annotations

import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from config import settings
from core import self_coder, sentinel
from core.sentinel import PuertoAbierto
from tools import seguridad_tools


def _puerto(puerto, ip="0.0.0.0", proceso="app.exe", ruta=r"C:\Program Files\App\app.exe", pid=1234):
    return PuertoAbierto(puerto, ip, pid, proceso, ruta)


class GravedadTests(unittest.TestCase):
    def test_gravedad_segun_exposicion_y_ubicacion(self) -> None:
        self.assertEqual(_puerto(3000, ip="127.0.0.1").gravedad(), "bajo")                   # solo este PC
        self.assertEqual(_puerto(3307).gravedad(), "medio")                                   # expuesto
        self.assertEqual(_puerto(4444, ruta=r"C:\Users\c\Downloads\x.exe").gravedad(), "alto")
        self.assertEqual(_puerto(4444, ruta=r"C:\Users\c\AppData\Local\Temp\x.exe").gravedad(), "alto")
        self.assertEqual(_puerto(49664, proceso="lsass.exe", ruta=r"C:\Windows\System32\lsass.exe").gravedad(), "bajo")

    def test_los_servicios_del_asistente_no_son_amenaza(self) -> None:
        self.assertTrue(sentinel.es_propio(_puerto(settings.WEB_PORT, ip="127.0.0.1")))
        self.assertTrue(sentinel.es_propio(_puerto(5432, proceso="postgres.exe",
                                                   ruta=r"C:\Users\c\.pg0\installation\bin\postgres.exe")))
        self.assertFalse(sentinel.es_propio(_puerto(3307, proceso="mysqld.exe")))


class AvisosTests(unittest.TestCase):
    def _centinela(self):
        avisos = []
        with patch.object(sentinel, "puertos_abiertos", return_value={}):
            c = sentinel.Sentinel(avisar=lambda texto, gravedad: avisos.append((gravedad, texto)))
        return c, avisos

    def test_solo_avisa_de_puertos_nuevos_y_expuestos(self) -> None:
        c, avisos = self._centinela()
        nuevos = {("0.0.0.0", 4444): _puerto(4444, ruta=r"C:\Users\c\Downloads\raro.exe", proceso="raro.exe"),
                  ("127.0.0.1", 5173): _puerto(5173, ip="127.0.0.1", proceso="node.exe"),
                  ("0.0.0.0", 3307): _puerto(3307, proceso="mysqld.exe")}
        with patch.object(sentinel, "puertos_abiertos", return_value=nuevos):
            c.revisar_puertos()
            c.revisar_puertos()          # la segunda vez ya son conocidos: no repite
        gravedades = sorted(g for g, _ in avisos)
        self.assertEqual(gravedades, ["alto", "medio"])
        alto = next(t for g, t in avisos if g == "alto")
        self.assertIn("raro.exe (PID 1234) abrió el puerto 4444, expuesto a toda tu red", alto)
        self.assertIn("cierra el proceso 1234", alto)

    def test_error_copiado_avisa_una_vez(self) -> None:
        c, avisos = self._centinela()
        error = "Traceback (most recent call last):\n  File \"a.py\"\nKeyError: 'x'"
        with patch("pyperclip.paste", return_value=error):
            self.assertEqual(c.revisar_portapapeles(), "de Python")
            self.assertIsNone(c.revisar_portapapeles())   # mismo contenido: no repite
        self.assertEqual(len(avisos), 1)
        self.assertIn("revisa el error que copié", avisos[0][1])
        self.assertIsNone(sentinel.error_copiado("lista de compras: leche, pan"))

    def test_bateria_baja_sin_cargador(self) -> None:
        c, avisos = self._centinela()
        with patch.object(sentinel.psutil, "sensors_battery", return_value=SimpleNamespace(percent=15, power_plugged=False)), \
             patch.object(c, "_gpu", return_value=(50.0, 1000.0)), patch.object(c, "revisar_puertos"), \
             patch.object(c, "revisar_portapapeles"):
            c.check_once()
        self.assertTrue(any("Batería al 15 %" in t for _, t in avisos))


class CerrarProcesoTests(unittest.TestCase):
    def test_nunca_cierra_windows_ni_el_asistente(self) -> None:
        import os
        self.assertIn("No cierro", seguridad_tools.cerrar_proceso(os.getpid()))
        self.assertIn("No hay ningún proceso", seguridad_tools.cerrar_proceso(999999))

    def test_cierra_solo_con_confirmacion(self) -> None:
        proceso = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        try:
            token = self_coder.confirmation_context(False)
            try:
                self.assertIn("necesito tu confirmación", seguridad_tools.cerrar_proceso(proceso.pid))
            finally:
                self_coder.reset_confirmation_context(token)
            with patch.object(self_coder.Confirm, "ask", return_value=False):
                self.assertEqual(seguridad_tools.cerrar_proceso(proceso.pid), "No lo cerré.")
            self.assertIsNone(proceso.poll())
            with patch.object(self_coder.Confirm, "ask", return_value=True):
                self.assertIn("Hecho", seguridad_tools.cerrar_proceso(proceso.pid))
            self.assertIsNotNone(proceso.wait(timeout=10))
        finally:
            if proceso.poll() is None:
                proceso.kill()


if __name__ == "__main__":
    unittest.main()
