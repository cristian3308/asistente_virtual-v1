"""Pruebas de humo de las habilidades y límites de lectura."""
from __future__ import annotations

import hashlib
import io
import shutil
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from config import settings
from core import self_coder
from tools import registry
from tools import browser_tools, dev_sec_tools
from tools.web_tools import leer_documentacion_web


class SmokeTests(unittest.TestCase):
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
        candidates = __import__("tools.custom_skills.abrir_aplicacion", fromlist=["_buscar_candidatos"])._buscar_candidatos("notepad")
        self.assertTrue(candidates)
        with patch.object(self_coder.Confirm, "ask", return_value=True), redirect_stdout(io.StringIO()):
            self_coder.cargar_habilidades_guardadas()
        with patch.object(registry, "_invoke_custom_with_timeout", return_value="notepad.EXE encontrado"):
            result = registry.call_tool("abrir_aplicacion", '{"nombre_aplicacion":"notepad"}')
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
