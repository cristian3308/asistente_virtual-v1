"""Pruebas del encadenamiento local, reglas, procedimientos, contexto de ventana y auto-reparación."""
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

from core import self_coder
from core.brain import AssistantBrain
from memory import learning_loop, perfil, procedimientos
from tools import registry

LOCAL = SimpleNamespace(name="Local", model="l", is_local=True)


def _texto(t):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=t, tool_calls=None))])


def _herramienta(nombre, argumentos=None, n=0):
    llamada = SimpleNamespace(index=0, id=f"c{n}", function=SimpleNamespace(name=nombre, arguments=json.dumps(argumentos or {})))
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=None, tool_calls=[llamada]))])


class RouterGuion:
    """Devuelve una respuesta por llamada y registra con qué herramientas se le llamó."""

    def __init__(self, guion):
        self.guion = list(guion)
        self.herramientas = []
        self.mensajes = []
        self.cloud_model = "c"

    def stream(self, prompt, prefer_cloud=False, messages=None, tools=None, **_kw):
        self.herramientas.append(tools)
        self.mensajes.append(messages)
        yield self.guion.pop(0), LOCAL


def _cerebro(router):
    brain = AssistantBrain.__new__(AssistantBrain)
    brain.router, brain.memory = router, MagicMock()
    brain.system_prompt = "reglas"
    brain.history = [{"role": "system", "content": "reglas"}]
    brain._show_tool_result = lambda *a: None
    return brain


class BaseTemporal(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="mejoras_"))
        self.parches = [patch.object(perfil, "DB_PATH", self.tmp / "perfil.db"),
                        patch.object(procedimientos, "DB_PATH", self.tmp / "proc.db"),
                        patch.object(learning_loop, "FAILURE_LOG", self.tmp / "fallos.jsonl")]
        for p in self.parches:
            p.start()

    def tearDown(self) -> None:
        for p in self.parches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)


class EncadenamientoLocalTests(BaseTemporal):
    def test_modelo_local_encadena_herramientas_distintas(self) -> None:
        router = RouterGuion([_herramienta("uno", n=1), _herramienta("dos", {"x": 1}, n=2), _texto("Listo.")])
        with patch.dict(registry.FUNCTIONS, {"uno": lambda a: "resultado uno", "dos": lambda a: "resultado dos"}), \
                redirect_stdout(io.StringIO()):
            respuesta, _ = _cerebro(router).ask("haz las dos cosas")
        self.assertEqual(respuesta, "Listo.")
        self.assertTrue(router.herramientas[1])        # tras la 1.ª herramienta sigue teniendo herramientas

    def test_repetir_la_misma_llamada_fuerza_la_respuesta(self) -> None:
        llamadas = []
        router = RouterGuion([_herramienta("ram", n=1), _herramienta("ram", n=2), _texto("Usas 15 GB.")])
        with patch.dict(registry.FUNCTIONS, {"ram": lambda a: llamadas.append(a) or "15 GB"}), redirect_stdout(io.StringIO()):
            respuesta, _ = _cerebro(router).ask("¿cuánta ram?")
        self.assertEqual(len(llamadas), 1)
        self.assertFalse(router.herramientas[2])        # sin herramientas: debe responder
        self.assertEqual(respuesta, "Usas 15 GB.")

    def test_tope_de_herramientas_en_local(self) -> None:
        guion = [_herramienta(f"h{i}", n=i) for i in range(3)] + [_texto("Fin.")]
        router = RouterGuion(guion)
        with patch.dict(registry.FUNCTIONS, {f"h{i}": (lambda a: "ok") for i in range(3)}), redirect_stdout(io.StringIO()):
            _cerebro(router).ask("varias cosas")
        self.assertFalse(router.herramientas[3])


class ReglasYProcedimientosTests(BaseTemporal):
    def test_reglas_se_inyectan_como_instrucciones(self) -> None:
        perfil.aprender_de("Siempre respóndeme en español y corto. Me gusta el café")
        perfil.aprender_de("No uses Chrome, usa Brave")
        instrucciones = _cerebro(None)._mensajes_con_memoria("hola")[0]["content"]
        bloque_reglas = instrucciones.split("REGLAS QUE CRISTHIAN TE DIO")[1]
        self.assertIn("No uses Chrome; usa Brave", bloque_reglas)
        self.assertNotIn("No uses Chrome", instrucciones.split("REGLAS QUE CRISTHIAN TE DIO")[0])

    def test_aprende_la_receta_y_la_sugiere_despues(self) -> None:
        router = RouterGuion([_herramienta("auditar_puertos_locales", n=1), _herramienta("listar_procesos_pesados", n=2),
                              _texto("El puerto 8080 es de python.exe.")])
        with patch.dict(registry.FUNCTIONS, {"auditar_puertos_locales": lambda a: "8080 python.exe",
                                             "listar_procesos_pesados": lambda a: "python.exe 300 MB"}), \
                redirect_stdout(io.StringIO()):
            _cerebro(router).ask("revisa qué programa usa el puerto sospechoso")
        guia = procedimientos.guia_para_modelo("revisa qué programa usa ese puerto raro")
        self.assertIn("auditar_puertos_locales", guia)
        self.assertIn("listar_procesos_pesados", guia)
        self.assertEqual(procedimientos.guia_para_modelo("cuéntame un chiste"), "")

    def test_contexto_de_ventana_solo_cuando_hablas_de_la_pantalla(self) -> None:
        with patch("tools.system_tools.ventana_activa", return_value="Antes de escribirme estabas en: «main.py - VS Code»"):
            con = _cerebro(None)._mensajes_con_memoria("¿por qué me sale este error?")[0]["content"]
            sin = _cerebro(None)._mensajes_con_memoria("hola, ¿cómo estás?")[0]["content"]
        self.assertIn("VS Code", con)
        self.assertNotIn("VS Code", sin)


class AutoReparacionTests(BaseTemporal):
    def test_fallo_de_habilidad_se_registra_y_se_ofrece_reparar(self) -> None:
        objetivo = SimpleNamespace(__name__="dividir", _custom_path="x.py")
        envoltorio = MagicMock(_tool_target=objetivo)
        with patch.dict(registry.FUNCTIONS, {"dividir": envoltorio}), \
                patch.object(registry, "_invoke_custom_with_timeout", return_value="Error en habilidad aislada: ZeroDivisionError"), \
                patch.object(registry, "_invoke_arguments", side_effect=lambda f, a: a):
            resultado = registry.call_tool("dividir", '{"a": 1, "b": 0}')
        self.assertIn('reparar_habilidad(nombre="dividir")', resultado)
        self.assertEqual(learning_loop.ultimo_fallo("dividir")["argumentos"], {"a": 1, "b": 0})

    def test_reparar_usa_el_caso_que_fallo_como_prueba(self) -> None:
        carpeta = self.tmp / "skills"
        carpeta.mkdir()
        (carpeta / "dividir.py").write_text("def dividir(a: int = 0, b: int = 1) -> str:\n    return str(a / b)\n", encoding="utf-8")
        learning_loop.registrar_fallo_habilidad("dividir", {"a": 1, "b": 0}, "ZeroDivisionError: division by zero")
        with patch.object(self_coder, "CUSTOM_DIR", carpeta), \
                patch.object(self_coder, "forjar_con_pruebas", return_value="reparada") as forjar:
            self.assertEqual(self_coder.reparar_habilidad("dividir"), "reparada")
        objetivo, nombre = forjar.call_args.args
        self.assertEqual(nombre, "dividir")
        self.assertIn("return str(a / b)", objetivo)
        self.assertIn('{"a": 1, "b": 0}', objetivo)
        self.assertIn("ZeroDivisionError", objetivo)
        self.assertIn("No conozco", self_coder.reparar_habilidad("no_existe"))


if __name__ == "__main__":
    unittest.main()
