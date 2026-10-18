"""Pruebas del aprendizaje automático, el escalado a la nube y la memoria."""
from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from config import settings
from core import self_coder
from core.brain import AssistantBrain
from core.router import ModelRouter, Motor
from tools import registry


def _chunk(text: str) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text, tool_calls=None))])


def _brain_with(router) -> AssistantBrain:
    brain = AssistantBrain.__new__(AssistantBrain)
    brain.router = router
    brain.memory = MagicMock()
    brain.system_prompt = "reglas"
    brain.history = [{"role": "system", "content": "reglas"}]
    return brain


class FiltroDeHerramientasTests(unittest.TestCase):
    def tearDown(self) -> None:
        registry.unregister_custom_tool("dias_hasta_fecha")

    def _names(self, prompt: str) -> list[str]:
        return [tool["function"]["name"] for tool in registry.obtener_herramientas_relevantes(prompt, True) or []]

    def test_plurales_activan_su_grupo(self) -> None:
        self.assertIn("listar_procesos_pesados", self._names("¿Qué procesos consumen más memoria?"))
        self.assertIn("listar_habilidades_disponibles", self._names("¿Qué habilidades tienes?"))

    def test_habilidad_aprendida_se_ofrece_solo_si_tiene_relacion(self) -> None:
        registry.register_custom_tool("dias_hasta_fecha", "Calcula cuántos días faltan hasta una fecha",
                                      lambda fecha="": fecha)
        self.assertEqual(self._names("¿Cuántos días faltan para el 2026-12-24?")[0], "dias_hasta_fecha")
        self.assertEqual(self._names("Hola, ¿cómo estás?"), [])

    def test_peticion_operativa_sin_herramienta_activa_la_forja(self) -> None:
        self.assertIn("autoprogramar_habilidad", self._names("cuenta las palabras de este texto: hola mundo"))


class RouterTests(unittest.TestCase):
    def test_lista_explicita_se_respeta_y_la_vacia_se_omite(self) -> None:
        motor = Motor(client=None, model="m", name="Local")
        only = [registry.TOOL_SCHEMAS[0]]
        self.assertIs(ModelRouter._with_tools_for(motor, "hola", {"tools": only, "tool_choice": "auto"})["tools"], only)
        empty = ModelRouter._with_tools_for(motor, "hola", {"tools": [], "tool_choice": "none"})
        self.assertNotIn("tools", empty)
        self.assertNotIn("tool_choice", empty)

    def test_prefer_cloud_pone_la_nube_primero(self) -> None:
        with patch.object(settings, "ollama_activo", return_value=True), \
                patch.object(settings, "cloud_configurado", return_value=True):
            router = ModelRouter()
            self.assertEqual([m.name for m in router.candidates("hola")], ["Local", "Cloud"])
            self.assertEqual([m.name for m in router.candidates("hola", prefer_cloud=True)], ["Cloud", "Local"])

    def test_corte_a_mitad_de_stream_no_mezcla_motores(self) -> None:
        def broken(**_kwargs):
            yield _chunk("Hola, esto es")
            raise ConnectionError("conexión perdida")

        local = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: broken())))
        cloud = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=MagicMock())))
        router = ModelRouter.__new__(ModelRouter)
        router.candidates = lambda prompt, prefer_cloud=False: [Motor(local, "m", "Local"), Motor(cloud, "c", "Cloud")]
        with self.assertRaises(RuntimeError):
            list(router.stream("hola", messages=[]))
        cloud.chat.completions.create.assert_not_called()


class EscaladoTests(unittest.TestCase):
    def test_motivos_de_escalado(self) -> None:
        brain = _brain_with(None)
        with patch.object(settings, "cloud_configurado", return_value=True), patch.object(settings, "AUTO_ESCALATE", True):
            local = {"local": True, "tools_run": 0}
            self.assertIsNotNone(brain._escalation_reason("Lo siento, no tengo la capacidad para abrir aplicaciones.", local))
            self.assertIsNotNone(brain._escalation_reason("¡Genial! Abriendo tu aplicación de Spotify.", local))
            self.assertIsNotNone(brain._escalation_reason("", local))
            self.assertIsNone(brain._escalation_reason("Estás usando 15 GB de RAM.", local))
            self.assertIsNone(brain._escalation_reason("No puedo abrirla.", {"local": True, "tools_run": 1}))
            self.assertIsNone(brain._escalation_reason("No tengo la capacidad.", {"local": False, "tools_run": 0}))
        with patch.object(settings, "cloud_configurado", return_value=True), patch.object(settings, "AUTO_ESCALATE", False):
            self.assertIsNone(brain._escalation_reason("No tengo la capacidad.", {"local": True, "tools_run": 0}))

    def test_ask_repite_el_turno_en_la_nube(self) -> None:
        calls = []

        def stream(prompt, prefer_cloud=False, **_kwargs):
            calls.append(prefer_cloud)
            if prefer_cloud:
                yield _chunk("Listo, te lo explico."), SimpleNamespace(name="Cloud", model="c", is_local=False)
            else:
                yield _chunk("Lo siento, no tengo la capacidad para eso."), SimpleNamespace(name="Local", model="l", is_local=True)

        router = SimpleNamespace(stream=stream, cloud_model="c")
        brain = _brain_with(router)
        with patch.object(settings, "cloud_configurado", return_value=True), patch.object(settings, "AUTO_ESCALATE", True), \
                redirect_stdout(io.StringIO()):
            answer, motor = brain.ask("explícame algo")
        self.assertEqual(answer, "Listo, te lo explico.")
        self.assertTrue(motor.startswith("Cloud"))
        self.assertEqual(calls, [False, True])
        self.assertEqual([m["role"] for m in brain.history], ["system", "user", "assistant"])


class OrdenesDirectasTests(unittest.TestCase):
    CASOS = {
        "abre spotify": ("abrir_aplicacion", {"nombre_aplicacion": "spotify"}),
        "Abre la aplicación de Copilot": ("abrir_aplicacion", {"nombre_aplicacion": "Copilot"}),
        "abrir word por favor": ("abrir_aplicacion", {"nombre_aplicacion": "word"}),
        "abre la carpeta tools": None,
        "abre spotify y pon música": None,
        "que aplicaciones tengo": ("listar_aplicaciones", {}),
        "¿tengo instalado discord?": ("listar_aplicaciones", {"filtro": "discord"}),
        "tienes la de spotify": ("listar_aplicaciones", {"filtro": "spotify"}),
        "¿tengo algo que hacer hoy?": None,
        "si no sabes como encontrar aplicaciones crea una habilidad": None,
    }

    def test_ordenes_inequivocas_no_pasan_por_el_modelo(self) -> None:
        brain = _brain_with(None)
        with patch.dict(registry.FUNCTIONS, {"abrir_aplicacion": lambda a: "ok"}):
            for prompt, esperado in self.CASOS.items():
                with self.subTest(prompt=prompt):
                    self.assertEqual(brain._orden_directa(prompt), esperado)

    def test_abrir_se_ejecuta_sin_llamar_al_modelo(self) -> None:
        router = SimpleNamespace(stream=MagicMock(side_effect=AssertionError("no debe llamar al modelo")))
        brain = _brain_with(router)
        with patch.dict(registry.FUNCTIONS, {"abrir_aplicacion": lambda a: f"Aplicación abierta: {a['nombre_aplicacion']}"}), \
                redirect_stdout(io.StringIO()):
            answer, motor = brain.ask("abre spotify")
        self.assertEqual(answer, "Aplicación abierta: spotify")
        self.assertEqual(motor, "Directo · abrir_aplicacion")

    def test_listar_aplicaciones_filtra_lo_instalado(self) -> None:
        from tools import system_tools
        apps = [{"Name": "Spotify", "AppID": "a"}, {"Name": "Calculadora", "AppID": "b"}]
        with patch.object(system_tools, "aplicaciones_menu_inicio", return_value=apps):
            self.assertIn("Spotify", system_tools.listar_aplicaciones("spotify"))
            self.assertIn("No hay ninguna", system_tools.listar_aplicaciones("zzz"))
            self.assertIn("(2)", system_tools.listar_aplicaciones())


class EscaladoFrasesRealesTests(unittest.TestCase):
    """Frases que el modelo local dijo de verdad sin ejecutar nada."""

    def test_detecta_negativas_y_acciones_fingidas(self) -> None:
        brain = _brain_with(None)
        frases = [
            "No tengo habilidad para abrir aplicaciones. Te sugiero que busques cómo abrir Spotify.",
            "No tengo conocimiento de una aplicación que se llame Copilot. Te aconsejo que busques información.",
            "Lo siento, pero no puedo crear habilidades en tiempo real.",
            "Abrindo Spotify... Por favor, espera mientras spotify carga.",
            "La solicitud para abrir Word ya fue hecha. Recuerda verificar en tu escritorio.",
        ]
        with patch.object(settings, "cloud_configurado", return_value=True), patch.object(settings, "AUTO_ESCALATE", True):
            for frase in frases:
                with self.subTest(frase=frase):
                    self.assertIsNotNone(brain._escalation_reason(frase, {"local": True, "tools_run": 0}))
            esquema = {"local": True, "tools_run": 0, "json_roto": True}
            self.assertIsNotNone(brain._escalation_reason('Guardando recuerdos: {"categoria":{"type":"string"}}', esquema))

    def test_respuesta_corta_tras_pregunta_de_la_nube_sigue_en_la_nube(self) -> None:
        calls = []

        def stream(prompt, prefer_cloud=False, **_kwargs):
            calls.append(prefer_cloud)
            yield _chunk("Hecho."), SimpleNamespace(name="Cloud", model="c", is_local=False)

        brain = _brain_with(SimpleNamespace(stream=stream, cloud_model="c"))
        brain._last_turn_cloud = True
        with redirect_stdout(io.StringIO()):
            brain.ask("sí, hazlo")
        self.assertEqual(calls, [True])


class ForjaConPruebasTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="forja_test_"))
        (self.tmp / "skills").mkdir()

    def tearDown(self) -> None:
        registry.unregister_custom_tool("contar_palabras")
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def _respuesta(codigo: str) -> SimpleNamespace:
        contenido = json.dumps({
            "nombre_funcion": "contar_palabras",
            "descripcion": "Cuenta las palabras de un texto",
            "codigo_python": codigo,
            "pruebas": [{"argumentos": {"texto": "hola mundo bonito"}, "contiene": "3 palabras"}],
        })
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=contenido))])

    def test_repara_con_el_error_de_las_pruebas_y_luego_instala(self) -> None:
        malo = "import re\n\ndef contar_palabras(texto: str = '') -> str:\n    return f'{len(texto)} palabras'\n"
        bueno = ("import re\n\ndef contar_palabras(texto: str = '') -> str:\n"
                 "    total = len(re.findall(r'\\w+', texto))\n    return f'{total} palabras'\n")
        client = MagicMock()
        client.chat.completions.create.side_effect = [self._respuesta(malo), self._respuesta(bueno)]
        with patch.object(self_coder, "_motores_de_forja", return_value=[(client, "m", "Cloud", {})]), \
                patch.object(self_coder, "CUSTOM_DIR", self.tmp / "skills"), \
                patch.object(self_coder, "MANIFEST_PATH", self.tmp / "skills" / "manifest.json"), \
                patch.object(settings, "DATA_DIR", self.tmp), \
                patch.object(self_coder.Confirm, "ask", return_value=True), redirect_stdout(io.StringIO()):
            resultado = self_coder.forjar_con_pruebas("contar las palabras de un texto", "contar_palabras")
        self.assertIn("Habilidad aprendida y lista: contar_palabras(texto: str = '')", resultado)
        self.assertEqual(client.chat.completions.create.call_count, 2)
        reparacion = client.chat.completions.create.call_args_list[1].kwargs["messages"][-1]["content"]
        self.assertIn("Fallaron estas pruebas", reparacion)
        self.assertEqual(self_coder.ULTIMA_HABILIDAD, "contar_palabras")
        self.assertEqual(registry.call_tool("contar_palabras", '{"texto": "uno dos"}'), "2 palabras")

    def test_no_instala_si_el_usuario_rechaza(self) -> None:
        bueno = "def contar_palabras(texto: str = '') -> str:\n    return f'{len(texto.split())} palabras'\n"
        client = MagicMock()
        client.chat.completions.create.return_value = self._respuesta(bueno)
        with patch.object(self_coder, "_motores_de_forja", return_value=[(client, "m", "Cloud", {})]), \
                patch.object(self_coder, "CUSTOM_DIR", self.tmp / "skills"), \
                patch.object(self_coder, "MANIFEST_PATH", self.tmp / "skills" / "manifest.json"), \
                patch.object(settings, "DATA_DIR", self.tmp), \
                patch.object(self_coder.Confirm, "ask", return_value=False), redirect_stdout(io.StringIO()):
            resultado = self_coder.forjar_con_pruebas("contar palabras", "contar_palabras")
        self.assertIn("rechazada", resultado)
        self.assertFalse((self.tmp / "skills" / "contar_palabras.py").exists())

    def test_tarea_imposible_termina_sin_gastar_mas_llamadas(self) -> None:
        client = MagicMock()
        imposible = '```json\n{"imposible": "necesita leer el registro de Windows"}\n```'
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=imposible))])
        with patch.object(self_coder, "_motores_de_forja", return_value=[(client, "m", "Cloud", {})] * 2):
            resultado = self_coder.forjar_con_pruebas("listar apps del registro", "buscar_apps")
        self.assertIn("No puedo aprender esto", resultado)
        self.assertEqual(client.chat.completions.create.call_count, 1)

    def test_limite_total_de_llamadas(self) -> None:
        client = MagicMock()
        client.chat.completions.create.return_value = self._respuesta("def contar_palabras(texto: str = '') -> str:\n    return 'mal'\n")
        with patch.object(self_coder, "_motores_de_forja", return_value=[(client, "m", "Cloud", {})] * 3), \
                patch.object(settings, "DATA_DIR", self.tmp), redirect_stdout(io.StringIO()):
            self_coder.forjar_con_pruebas("contar palabras", "contar_palabras")
        self.assertEqual(client.chat.completions.create.call_count, 5)

    def test_codigo_en_bloque_python_y_json_con_saltos_de_linea(self) -> None:
        raw = ("```python\ndef contar_palabras(texto: str = '') -> str:\n    return 'x'\n```\n"
               '```json\n{"nombre_funcion": "contar_palabras", "descripcion": "Cuenta\npalabras", '
               '"pruebas": [{"argumentos": {"texto": "a"}, "contiene": "x"}]}\n```')
        propuesta = self_coder._extraer_propuesta(raw, "contar_palabras")
        self.assertEqual(propuesta["nombre"], "contar_palabras")
        self.assertEqual(len(propuesta["pruebas"]), 1)

    def test_nombre_de_herramienta_integrada_no_se_pisa(self) -> None:
        self.assertEqual(self_coder._nombre_libre("estado_hardware"), "estado_hardware_aprendida")


class MemoriaTests(unittest.TestCase):
    def test_fallos_no_se_guardan_como_recuerdos(self) -> None:
        from memory import learning_loop
        tmp = Path(tempfile.mkdtemp(prefix="fallos_"))
        try:
            with patch.object(learning_loop, "FAILURE_LOG", tmp / "fallos.jsonl"), \
                    patch("tools.memory_tools.guardar_recuerdo_importante", side_effect=AssertionError("no debe usarse")):
                try:
                    raise ValueError("boom")
                except ValueError as exc:
                    learning_loop.registrar_fallo("demo", exc)
                self.assertEqual(learning_loop.fallos_recientes()[-1]["herramienta"], "demo")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_migra_la_coleccion_antigua_al_modelo_multilingue(self) -> None:
        import chromadb
        from memory import vector_rag
        tmp = Path(tempfile.mkdtemp(prefix="chroma_"))
        try:
            legacy = chromadb.PersistentClient(path=str(tmp)).get_or_create_collection("memoria_personal")
            legacy.add(ids=["1"], documents=["Me gusta programar en Python"], metadatas=[{"categoria": "gustos"}])
            with patch.object(vector_rag, "CHROMA_PATH", tmp):
                memoria = vector_rag.VectorMemory()
                self.assertEqual(memoria.personal.count(), 1)
                self.assertEqual(memoria.search("lenguaje de programación favorito")[0]["text"], "Me gusta programar en Python")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
