"""Pruebas de la memoria personal: detección, persistencia, uso en cada respuesta y olvido."""
from __future__ import annotations

import io
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core.brain import AssistantBrain
from memory import perfil
from tools import registry


def _chunk(texto: str) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=texto, tool_calls=None))])


class RouterQueGuarda:
    """Router falso que registra los mensajes que recibiría el modelo."""

    def __init__(self) -> None:
        self.vistos: list[list[dict]] = []
        self.cloud_model = "c"

    def stream(self, prompt, prefer_cloud=False, messages=None, **_kwargs):
        self.vistos.append(messages)
        yield _chunk("De acuerdo."), SimpleNamespace(name="Local", model="l", is_local=True)


def _cerebro(router) -> AssistantBrain:
    brain = AssistantBrain.__new__(AssistantBrain)
    brain.router = router
    brain.memory = MagicMock()
    brain.system_prompt = "reglas"
    brain.history = [{"role": "system", "content": "reglas"}]
    return brain


class MemoriaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="perfil_"))
        self.db = patch.object(perfil, "DB_PATH", self.tmp / "perfil.db")
        self.db.start()

    def tearDown(self) -> None:
        self.db.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_detecta_datos_y_no_confunde_preguntas(self) -> None:
        casos = {
            "Mi mamá se llama Jacky Lin y mi papá se llama Carlos.": [("mamá", "Jacky Lin", "familia"), ("papá", "Carlos", "familia")],
            "Me llamo Cristhian": [("nombre", "Cristhian", "identidad")],
            "No me gusta el reguetón": [("no le gusta", "el reguetón", "gustos")],
            "Recuerda que mañana tengo examen": [("nota", "mañana tengo examen", "nota")],
            "¿Cómo se llama mi mamá?": [],
            "me gustaría que abras word": [],
        }
        for frase, esperado in casos.items():
            with self.subTest(frase=frase):
                self.assertEqual(perfil.extraer_hechos(frase), esperado)

    def test_corregir_reemplaza_y_conserva_historico(self) -> None:
        perfil.aprender_de("Mi mamá se llama Jacky")
        perfil.aprender_de("Mi mamá se llama Jacky Lin")
        vigentes = [h for h in perfil.hechos() if h["clave"] == "mamá"]
        self.assertEqual([h["valor"] for h in vigentes], ["Jacky Lin"])
        self.assertEqual(len([h for h in perfil.hechos(incluir_historicos=True) if h["clave"] == "mamá"]), 2)

    def test_lo_dicho_llega_al_modelo_despues_de_reiniciar(self) -> None:
        primero = _cerebro(RouterQueGuarda())
        with redirect_stdout(io.StringIO()):
            primero.ask("Mi mamá se llama Jacky Lin y me gusta el café")
        self.assertIn("ACABAS DE GUARDAR", primero.router.vistos[0][0]["content"])
        # "Reinicio": cerebro nuevo, sin historial de conversación.
        despues = _cerebro(RouterQueGuarda())
        with redirect_stdout(io.StringIO()):
            despues.ask("¿Cómo se llama mi mamá?")
        instrucciones = despues.router.vistos[0][0]["content"]
        self.assertIn("mamá: Jacky Lin", instrucciones)
        self.assertIn("le gusta: el café", instrucciones)
        self.assertNotIn("ACABAS DE GUARDAR", instrucciones)

    def test_olvidar_por_conversacion(self) -> None:
        perfil.aprender_de("Me gusta el café")
        brain = _cerebro(SimpleNamespace(stream=MagicMock(side_effect=AssertionError("no debe llamar al modelo"))))
        respuesta, motor = brain.ask("olvida que me gusta el café")
        self.assertEqual(motor, "Memoria")
        self.assertIn("olvidé 1", respuesta)
        self.assertEqual(perfil.hechos(), [])

    def test_lo_que_guarda_el_modelo_tambien_va_al_perfil(self) -> None:
        from tools import memory_tools
        with patch.object(memory_tools, "get_vector_memory") as vector:
            vector.return_value.remember.return_value = "Recuerdo guardado."
            memory_tools.guardar_recuerdo_importante("Su color favorito es el azul", "gustos")
        self.assertIn("Su color favorito es el azul", perfil.resumen_para_modelo())


class OrdenesNuevasTests(unittest.TestCase):
    def test_puedes_abrir_word(self) -> None:
        brain = _cerebro(None)
        with patch.dict(registry.FUNCTIONS, {"abrir_aplicacion": lambda a: "ok"}):
            for frase in ("puedes abrir word", "¿me puedes abrir Spotify?", "abre word porfa"):
                with self.subTest(frase=frase):
                    self.assertEqual(brain._orden_directa(frase)[0], "abrir_aplicacion")

    def test_investigar_resume_con_fuentes_y_trata_la_web_como_datos(self) -> None:
        from tools import web_tools
        resultados = [{"title": "Python 3.14", "href": "https://python.org/a", "body": "Nueva versión"}]
        respuesta = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="Salió Python 3.14 [1]."))])
        with patch("ddgs.DDGS") as ddgs, patch.object(web_tools, "leer_documentacion_web", return_value="Detalles"), \
                patch("core.router.ModelRouter.complete", return_value=(respuesta, None)) as completar:
            ddgs.return_value.text.return_value = resultados
            texto = web_tools.investigar_tema("última versión de Python")
        self.assertIn("Salió Python 3.14 [1].", texto)
        self.assertIn("https://python.org/a", texto)
        self.assertIn("NO confiable", completar.call_args.kwargs["messages"][0]["content"])
        self.assertIn("investigar_tema", [t["function"]["name"] for t in registry.obtener_herramientas_relevantes("investiga sobre Python y hazme un resumen", True)])


if __name__ == "__main__":
    unittest.main()
