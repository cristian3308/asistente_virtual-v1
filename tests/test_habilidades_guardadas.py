"""Las habilidades aprobadas cargan solas al reiniciar; las modificadas vuelven a pedir permiso."""
from __future__ import annotations

import hashlib
import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from core import self_coder

CODIGO = "def sumar_tres(numero: int) -> str:\n    \"\"\"Suma tres.\"\"\"\n    return str(numero + 3)"   # sin salto final


class HabilidadesGuardadasTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="habilidades_"))
        self.parches = [patch.object(self_coder, "CUSTOM_DIR", self.tmp),
                        patch.object(self_coder, "MANIFEST_PATH", self.tmp / "manifest.json")]
        for p in self.parches:
            p.start()

    def tearDown(self) -> None:
        for p in self.parches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _cargar_sin_preguntar(self) -> list[str]:
        with patch.object(self_coder.Confirm, "ask", side_effect=AssertionError("no debe preguntar")), \
             redirect_stdout(io.StringIO()):
            return self_coder.cargar_habilidades_guardadas()

    def test_aprobada_no_vuelve_a_preguntar_al_reiniciar(self) -> None:
        with patch.object(self_coder.Confirm, "ask", return_value=True), redirect_stdout(io.StringIO()):
            self_coder.crear_y_cargar_herramienta("sumar_tres", "Suma tres", CODIGO)
        self.assertEqual(self._cargar_sin_preguntar(), ["sumar_tres"])

    def test_huella_antigua_sin_salto_final_se_corrige_una_vez(self) -> None:
        (self.tmp / "sumar_tres.py").write_text(CODIGO + "\n", encoding="utf-8")
        (self.tmp / "manifest.json").write_text(json.dumps([{
            "name": "sumar_tres", "description": "Suma tres", "file": "sumar_tres.py", "approved": True,
            "sha256": hashlib.sha256(CODIGO.encode("utf-8")).hexdigest()}]), encoding="utf-8")
        self.assertEqual(self._cargar_sin_preguntar(), ["sumar_tres"])
        manifiesto = json.loads((self.tmp / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifiesto[0]["sha256"], hashlib.sha256((CODIGO + "\n").encode("utf-8")).hexdigest())

    def test_codigo_modificado_pide_permiso_otra_vez(self) -> None:
        with patch.object(self_coder.Confirm, "ask", return_value=True), redirect_stdout(io.StringIO()):
            self_coder.crear_y_cargar_herramienta("sumar_tres", "Suma tres", CODIGO)
        (self.tmp / "sumar_tres.py").write_text(CODIGO.replace("+ 3", "+ 4") + "\n", encoding="utf-8")
        with patch.object(self_coder.Confirm, "ask", return_value=False) as pregunta, redirect_stdout(io.StringIO()):
            self.assertEqual(self_coder.cargar_habilidades_guardadas(), [])
        pregunta.assert_called_once()


if __name__ == "__main__":
    unittest.main()
