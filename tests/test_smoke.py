"""Pruebas de humo de las habilidades y límites de lectura."""
from __future__ import annotations

import hashlib
import io
import shutil
from types import SimpleNamespace
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from config import settings
from core import self_coder
from core.brain import AssistantBrain
from core.router import ModelRouter
from tools import registry
from tools import browser_tools, dev_sec_tools
from tools.custom_skills import abrir_aplicacion as app_skill
from tools.web_tools import leer_documentacion_web


class SmokeTests(unittest.TestCase):
    def test_local_text_tool_call_allows_trailing_text(self) -> None:
        call = AssistantBrain._parse_text_tool_call(
            '{"name": "estado_hardware", "arguments": {}}\nUna vez que el servicio proporciona la información, podré mostrarla.'
        )
        self.assertIsNotNone(call)
        self.assertEqual(call["name"], "estado_hardware")

    def test_local_context_budget_keeps_system_and_current_request(self) -> None:
        messages = [{"role": "system", "content": "reglas " * 30}]
        messages.extend({"role": "assistant", "content": f"antiguo {index} " * 100} for index in range(12))
        messages.append({"role": "user", "content": "petición actual " * 20})
        trimmed = ModelRouter._trim_local_messages(messages, 1400)
        self.assertEqual(trimmed[0]["role"], "system")
        self.assertEqual(trimmed[-1]["content"], messages[-1]["content"])
        self.assertLessEqual(sum(ModelRouter._estimate_tokens(message) for message in trimmed), 1400)

    def test_local_context_keeps_parallel_tool_calls_as_one_block(self) -> None:
        messages = [
            {"role": "system", "content": "rules"},
            {"role": "user", "content": "old request"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "a"}, {"id": "b"}]},
            {"role": "tool", "tool_call_id": "a", "content": "A" * 30},
            {"role": "tool", "tool_call_id": "b", "content": "B" * 30},
            {"role": "user", "content": "current request"},
        ]
        trimmed = ModelRouter._trim_local_messages(messages, 80)
        roles = [message["role"] for message in trimmed]
        self.assertEqual(roles[0], "system")
        self.assertEqual(roles[-1], "user")
        active_tool_calls = set()
        for index, message in enumerate(trimmed):
            if message["role"] == "assistant":
                active_tool_calls = {call["id"] for call in message.get("tool_calls", [])}
            if message["role"] == "tool":
                self.assertIn(message["tool_call_id"], active_tool_calls)

    def test_current_large_tool_block_is_compressed_not_dropped(self) -> None:
        messages = [
            {"role": "system", "content": "rules"},
            {"role": "user", "content": "current request"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "a"}, {"id": "b"}, {"id": "c"}]},
            {"role": "tool", "tool_call_id": "a", "content": "A" * 1500},
            {"role": "tool", "tool_call_id": "b", "content": "B" * 1500},
            {"role": "tool", "tool_call_id": "c", "content": "C" * 1500},
        ]
        trimmed = ModelRouter._trim_local_messages(messages, 100)
        self.assertEqual([message.get("tool_call_id") for message in trimmed if message["role"] == "tool"], ["a", "b", "c"])
        self.assertTrue(all(len(message["content"]) < 1500 for message in trimmed if message["role"] == "tool"))

    def test_manifest_skills_are_loadable_and_registered(self) -> None:
        for name in ("abrir_aplicacion", "calcular_sha256"):
            code = (self_coder.CUSTOM_DIR / f"{name}.py").read_text(encoding="utf-8")
            manifest_item = next(item for item in self_coder._manifest() if item["name"] == name)
            self.assertEqual(hashlib.sha256(code.encode("utf-8")).hexdigest(), manifest_item["sha256"].lower())
        with patch.object(self_coder.Confirm, "ask", return_value=True), redirect_stdout(io.StringIO()):
            loaded = self_coder.cargar_habilidades_guardadas()
        self.assertIn("abrir_aplicacion", loaded)
        self.assertIn("calcular_sha256", loaded)
        self.assertIn("abrir_aplicacion", registry.FUNCTIONS)
        self.assertIn("calcular_sha256", registry.FUNCTIONS)
        calc_schema = next(schema for schema in registry.TOOL_SCHEMAS if schema["function"]["name"] == "calcular_sha256")
        self.assertIn("ruta_archivo", calc_schema["function"]["parameters"]["properties"])
        call_result = registry.call_tool("calcular_sha256", '{"ruta_archivo":"tests/test_smoke.py"}')
        self.assertEqual(len(call_result), 64)
        target = registry.FUNCTIONS["calcular_sha256"]._tool_target
        isolated_result = registry._invoke_custom_with_timeout(target, {"ruta_archivo": str(Path(__file__))})
        self.assertEqual(len(isolated_result), 64)

    def test_private_and_database_paths_are_blocked(self) -> None:
        self.assertFalse(settings.path_is_allowed(settings.DATA_DIR / "memoria_sesiones.db"))
        self.assertFalse(settings.path_is_allowed(Path.home() / ".ssh" / "id_rsa"))
        self.assertIn("URL bloqueada", leer_documentacion_web("http://127.0.0.1:11434/"))

    def test_browser_blocks_private_url_without_runtime_error(self) -> None:
        result = browser_tools.automatizar_navegador("http://127.0.0.1:11434/")
        self.assertIn("URL bloqueada", result)

    @unittest.skipUnless(shutil.which("notepad") or shutil.which("notepad.exe"), "Notepad no está disponible")
    def test_call_tool_routes_open_app_without_scanning_program_files(self) -> None:
        with patch.object(self_coder.Confirm, "ask", return_value=True), redirect_stdout(io.StringIO()):
            self_coder.cargar_habilidades_guardadas()
        skill_path = self_coder.CUSTOM_DIR / "abrir_aplicacion.py"
        target = SimpleNamespace(_custom_path=str(skill_path), __name__="_buscar_candidatos")
        result = registry._invoke_custom_with_timeout(target, {"nombre": "notepad"})
        self.assertIn("notepad", result.lower())

    def test_powershell_from_telegram_never_prompts(self) -> None:
        token = self_coder.confirmation_context(False)
        try:
            with patch.object(dev_sec_tools.Confirm, "ask") as ask:
                result = dev_sec_tools.ejecutar_powershell_seguro("Write-Output hola")
            ask.assert_not_called()
        finally:
            self_coder.reset_confirmation_context(token)
        self.assertIn("Requiere consola local", result)

    def test_app_partial_match_is_not_opened_and_alias_is_exact(self) -> None:
        with patch.object(app_skill, "_buscar_candidatos", return_value=[Path("Discord.lnk")]), patch.object(app_skill.os, "startfile") as startfile:
            result = app_skill.abrir_aplicacion("discordia")
        self.assertIn("coincidencias", result)
        startfile.assert_not_called()
        with patch.object(app_skill, "_buscar_candidatos", return_value=[Path("calc.exe")]), patch.object(app_skill.os, "startfile") as startfile:
            result = app_skill.abrir_aplicacion("calculadora")
        self.assertIn("Aplicación abierta", result)
        startfile.assert_called_once()
        with patch.object(app_skill, "_buscar_candidatos", return_value=[Path("Google Chrome.lnk")]), patch.object(app_skill.os, "startfile") as startfile:
            result = app_skill.abrir_aplicacion("chrome")
        self.assertIn("Aplicación abierta", result)
        startfile.assert_called_once()
        with patch.object(app_skill.os, "startfile") as startfile:
            result = app_skill.abrir_aplicacion("configuración")
        self.assertIn("configuración", result.lower())
        startfile.assert_called_once_with("ms-settings:")

    def test_generated_code_uses_a_restricted_ast_surface(self) -> None:
        rejected = (
            "import importlib\ndef prueba():\n    return 'x'",
            "def prueba():\n    return getattr(__builtins__, 'eval')('1')",
            "from urllib import request\ndef prueba():\n    return 'x'",
            "from pathlib import Path\ndef prueba():\n    return Path('x').unlink()",
            "import pathlib\ndef prueba():\n    return pathlib.sys.modules['subprocess']",
            "import pathlib\ndef prueba():\n    return pathlib.os.environ",
            "import pathlib\ndef prueba():\n    return pathlib.os.execv('x', [])",
            "import pathlib\ndef prueba():\n    return pathlib.os.spawnl(0, 'x')",
            "import pathlib\ndef prueba():\n    return pathlib.os.truncate('x', 0)",
            "import pathlib\ndef prueba():\n    return pathlib.io.FileIO('x', 'w')",
            "from pathlib import Path\ndef prueba():\n    return Path('.env').read_text()",
            "from pathlib import Path\ndef prueba():\n    return Path('x').open('w')",
            "def prueba():\n    for _ in range(10**12):\n        pass",
            "import pathlib\ndef prueba():\n    return pathlib.Path('x')._accessor",
            "@lambda fn: fn\ndef prueba():\n    return 'x'",
            "class A:\n    x = 1\ndef prueba():\n    return 'x'",
            "X = 'a' * 10**11\ndef prueba():\n    return 'x'",
        )
        for code in rejected:
            with self.subTest(code=code):
                with self.assertRaises(ValueError):
                    self_coder._validate("prueba", code)


if __name__ == "__main__":
    unittest.main()
