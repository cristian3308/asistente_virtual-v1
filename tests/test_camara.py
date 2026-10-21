"""Cámara: reconocer, ver el ánimo y avisar, sin guardar imágenes (nunca abre la cámara real)."""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from core import camara
from tools import registry


class CapturaFalsa:
    def __init__(self) -> None:
        self.liberada = False

    def read(self):
        return True, np.zeros((480, 640, 3), np.uint8)

    def release(self):
        self.liberada = True


class OjosFalsos:
    """Devuelve una cara por foto y una huella fija: suficiente para probar la lógica."""

    def caras(self, imagen):
        return [np.array([10, 10, 100, 100] + [0] * 11, np.float32)]

    def huella(self, imagen, cara):
        return np.ones((1, 128), np.float32), imagen


class CamaraTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="camara_"))
        self.parche = patch.object(camara, "ROSTRO", self.tmp / "rostro.npy")
        self.parche.start()

    def tearDown(self) -> None:
        self.parche.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_registrar_guarda_solo_una_huella_numerica(self) -> None:
        cam = camara.Camara()
        cam._ojos, cam._captura = OjosFalsos(), CapturaFalsa()
        with patch.object(camara.time, "sleep"):
            mensaje = cam.registrar(fotos=4)
        self.assertIn("Ya te reconozco", mensaje)
        self.assertEqual(np.load(camara.ROSTRO).shape, (1, 128))
        self.assertEqual([p.name for p in self.tmp.iterdir()], ["rostro.npy"])   # ninguna foto
        self.assertIn("Olvidé", cam.olvidar())
        self.assertFalse(camara.ROSTRO.exists())

    def test_avisa_cuando_llegas_te_vas_o_hay_un_desconocido(self) -> None:
        np.save(camara.ROSTRO, np.ones((1, 128), np.float32))
        vistas = iter([
            {"caras": 1, "tu": True, "emocion": "feliz", "desconocidos": 0},
            {"caras": 0, "tu": False, "emocion": None, "desconocidos": 0},
            {"caras": 1, "tu": False, "emocion": None, "desconocidos": 1},
            {"caras": 1, "tu": True, "emocion": "neutral", "desconocidos": 0},
        ])
        eventos = []
        cam = camara.Camara(al_cambiar=lambda e, d: eventos.append(e))
        cam.mirar = lambda: next(vistas)
        espera = iter([False] * 4 + [True])
        cam._parar.wait = lambda _s: next(espera)
        cam._bucle()
        self.assertEqual(eventos, ["te_fuiste", "desconocido", "llegaste"])

    def test_animo_ignora_un_gesto_suelto(self) -> None:
        cam = camara.Camara()
        cam._emociones.extend(["neutral"] * 8 + ["sorprendido"])
        self.assertEqual(cam.animo(), "neutral")
        cam._emociones.clear()
        self.assertIsNone(cam.animo())

    def test_el_modelo_solo_lo_sabe_con_la_camara_encendida(self) -> None:
        cam = camara.Camara()
        self.assertEqual(cam.resumen(), "")
        with patch.object(cam, "encendida", return_value=True):
            cam.ultimo = {"presente": True, "hora": camara.time.time()}
            cam._emociones.extend(["feliz"] * 5)
            self.assertIn("parece feliz", cam.resumen())
            cam.ultimo = {"presente": False, "hora": camara.time.time()}
            self.assertIn("no está frente al PC", cam.resumen())

    def test_apagar_libera_la_camara(self) -> None:
        cam = camara.Camara()
        captura = CapturaFalsa()
        cam._captura = captura
        cam.apagar()
        self.assertTrue(captura.liberada)
        self.assertIsNone(cam._captura)

    def test_preguntar_si_me_ves_con_la_camara_apagada(self) -> None:
        with patch.object(camara, "_camara", camara.Camara()):
            self.assertIn("apagada", registry.FUNCTIONS["mirar_camara"]({}))
        nombres = [t["function"]["name"] for t in registry.obtener_herramientas_relevantes("¿me ves?", True)]
        self.assertIn("mirar_camara", nombres)


@unittest.skipUnless(camara.disponible(), "modelos de cámara no descargados")
class ModelosRealesTests(unittest.TestCase):
    def test_imagen_sin_caras(self) -> None:
        datos = camara.Ojos().analizar(np.full((480, 640, 3), 128, np.uint8))
        self.assertEqual(datos["caras"], 0)


if __name__ == "__main__":
    unittest.main()
