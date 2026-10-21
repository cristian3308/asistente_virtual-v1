"""YouTube, RSS, web y GitHub sin cuentas, y REA solo estático con confirmación (sin red)."""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from core import self_coder
from tools import internet_tools, rea_tools, registry


class InternetTests(unittest.TestCase):
    def test_reconoce_enlaces_de_youtube(self) -> None:
        casos = {
            "https://www.youtube.com/watch?v=aircAruvnKk&t=10": "aircAruvnKk",
            "https://youtu.be/dQw4w9WgXcQ": "dQw4w9WgXcQ",
            "https://www.youtube.com/shorts/abc123": "abc123",
            "https://vimeo.com/123": None,
            "https://youtube.com.malo.net/watch?v=x": None,
        }
        for url, esperado in casos.items():
            with self.subTest(url=url):
                self.assertEqual(internet_tools._id_youtube(url), esperado)
        self.assertIn("no parece un enlace de YouTube", internet_tools.resumir_video_youtube("https://vimeo.com/1"))

    def test_subtitulos_json3_a_texto(self) -> None:
        json3 = json.dumps({"events": [{"segs": [{"utf8": "Hola "}, {"utf8": "mundo"}]}, {"tStartMs": 1},
                                       {"segs": [{"utf8": "\nadiós"}]}]})
        self.assertEqual(internet_tools._texto_de_subtitulos(json3), "Hola mundo adiós")

    def test_repositorio_github_desde_enlace_o_nombre(self) -> None:
        self.assertEqual(internet_tools._repo_github("https://github.com/morluto/rea."), "morluto/rea")
        self.assertEqual(internet_tools._repo_github("vectorize-io/hindsight"), "vectorize-io/hindsight")
        self.assertIsNone(internet_tools._repo_github("hola"))

    def test_no_entra_a_la_red_local(self) -> None:
        for url in ("http://127.0.0.1:8780/", "http://localhost:11434", "file:///C:/Windows/win.ini", "http://192.168.1.1"):
            with self.subTest(url=url):
                self.assertTrue(internet_tools.leer_pagina(url).startswith("URL bloqueada"))
        self.assertTrue(internet_tools.leer_noticias_rss("http://10.0.0.5/rss").startswith("URL bloqueada"))

    def test_herramienta_correcta_primero_segun_el_enlace(self) -> None:
        nombres = lambda f: [t["function"]["name"] for t in registry.obtener_herramientas_relevantes(f, True)]
        self.assertEqual(nombres("resúmeme este video https://youtu.be/abc")[0], "resumir_video_youtube")
        self.assertEqual(nombres("qué es github.com/morluto/rea")[0], "resumir_repositorio_github")
        self.assertIn("leer_noticias_rss", nombres("léeme el feed rss de la bbc"))


class ReaTests(unittest.TestCase):
    def test_solo_analisis_estaticos_de_la_lista_blanca(self) -> None:
        self.assertEqual(set(rea_tools.ANALISIS.values()),
                         {"inspect-artifact", "analyze-javascript-application", "inspect-electron-fuses"})
        with patch.object(rea_tools, "disponible", return_value=True):
            self.assertIn("desconocido", rea_tools.analizar_programa("README.md", "debug-with-gdb"))

    def test_no_analiza_datos_privados(self) -> None:
        with patch.object(rea_tools, "disponible", return_value=True):
            self.assertIn("privados", rea_tools.analizar_programa(".env"))

    def test_desde_el_celular_o_telegram_no_se_autoriza(self) -> None:
        token = self_coder.confirmation_context(False)
        try:
            with patch.object(rea_tools, "disponible", return_value=True), \
                 patch.object(rea_tools.subprocess, "run", side_effect=AssertionError("no debe ejecutar REA")):
                self.assertIn("solo se autoriza desde la consola", rea_tools.analizar_programa("README.md"))
        finally:
            self_coder.reset_confirmation_context(token)

    def test_si_rechazas_no_se_ejecuta(self) -> None:
        with patch.object(rea_tools, "disponible", return_value=True), \
             patch.object(self_coder.Confirm, "ask", return_value=False), \
             patch.object(rea_tools.subprocess, "run", side_effect=AssertionError("no debe ejecutar REA")):
            self.assertIn("cancelado", rea_tools.analizar_programa("README.md"))


if __name__ == "__main__":
    unittest.main()
