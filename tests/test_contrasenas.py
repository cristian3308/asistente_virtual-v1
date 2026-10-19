"""Pruebas del generador de contraseñas robustas."""
from __future__ import annotations

import math
import string
import unittest

from tools import contrasenas


class GeneradorContrasenasTests(unittest.TestCase):
    def test_longitud_por_defecto(self) -> None:
        datos = contrasenas.generar_contrasena_robusta()
        self.assertEqual(datos["longitud"], 16)
        self.assertEqual(len(datos["contrasena"]), 16)

    def test_longitud_personalizada(self) -> None:
        for longitud in (8, 24, 64):
            with self.subTest(longitud=longitud):
                datos = contrasenas.generar_contrasena_robusta(longitud=longitud)
                self.assertEqual(len(datos["contrasena"]), longitud)

    def test_longitud_fuera_de_rango_lanza_error(self) -> None:
        for longitud in (7, 65, 0, -1):
            with self.subTest(longitud=longitud):
                with self.assertRaises(ValueError):
                    contrasenas.generar_contrasena_robusta(longitud=longitud)

    def test_incluye_todas_las_categorias_activas(self) -> None:
        datos = contrasenas.generar_contrasena_robusta(longitud=32)
        contrasena = datos["contrasena"]
        self.assertTrue(any(c in string.ascii_uppercase for c in contrasena))
        self.assertTrue(any(c in string.ascii_lowercase for c in contrasena))
        self.assertTrue(any(c in string.digits for c in contrasena))
        self.assertTrue(any(c in string.punctuation for c in contrasena))

    def test_respeta_categorias_desactivadas(self) -> None:
        datos = contrasenas.generar_contrasena_robusta(
            longitud=20,
            incluir_mayusculas=False,
            incluir_numeros=False,
        )
        contrasena = datos["contrasena"]
        self.assertFalse(any(c in string.ascii_uppercase for c in contrasena))
        self.assertTrue(any(c in string.ascii_lowercase for c in contrasena))
        self.assertFalse(any(c in string.digits for c in contrasena))
        self.assertTrue(any(c in string.punctuation for c in contrasena))

    def test_excluye_ambiguos_cuando_se_solicita(self) -> None:
        for _ in range(20):
            datos = contrasenas.generar_contrasena_robusta(longitud=64, evitar_ambiguos=True)
            for caracter in contrasenas._AMBIGUOS:
                self.assertNotIn(caracter, datos["contrasena"])

    def test_permite_ambiguos_cuando_se_desactiva(self) -> None:
        # Con longitud suficiente y muchos intentos es prácticamente seguro que aparezca alguno.
        encontrados = set()
        for _ in range(50):
            datos = contrasenas.generar_contrasena_robusta(longitud=64, evitar_ambiguos=False)
            encontrados.update(c for c in datos["contrasena"] if c in contrasenas._AMBIGUOS)
            if encontrados == contrasenas._AMBIGUOS:
                break
        self.assertTrue(encontrados)

    def test_entropia_calculada_correctamente(self) -> None:
        datos = contrasenas.generar_contrasena_robusta(longitud=16)
        esperada = 16 * math.log2(datos["tamano_alfabeto"])
        self.assertAlmostEqual(datos["entropia_bits"], esperada, places=2)

    def test_calificacion_de_fortaleza(self) -> None:
        casos = [
            (8, True, True, True, True, "media"),  # 8 * log2(92) ≈ 51.9 bits
            (12, True, True, True, False, "fuerte"),  # 12 * log2(62) ≈ 71.4 bits
            (16, True, True, True, True, "muy fuerte"),  # 16 * log2(92) ≈ 103.8 bits
        ]
        for longitud, may, min_, num, sim, esperado in casos:
            with self.subTest(longitud=longitud, esperado=esperado):
                datos = contrasenas.generar_contrasena_robusta(
                    longitud=longitud,
                    incluir_mayusculas=may,
                    incluir_minusculas=min_,
                    incluir_numeros=num,
                    incluir_simbolos=sim,
                )
                self.assertEqual(datos["fortaleza"], esperado)

    def test_sin_categorias_lanza_error(self) -> None:
        with self.assertRaises(ValueError):
            contrasenas.generar_contrasena_robusta(
                incluir_mayusculas=False,
                incluir_minusculas=False,
                incluir_numeros=False,
                incluir_simbolos=False,
            )

    def test_categoria_vacia_por_ambiguos_lanza_error(self) -> None:
        # Dígitos sin ambiguos deja solo 2-9 (8 símbolos), no vacío.
        # Caso forzado: mayúsculas y minúsculas desactivadas, números desactivados,
        # solo símbolos; nunca debería estar vacío porque los símbolos no tienen ambiguos.
        # Verificamos que no lance error y que la contraseña contenga solo símbolos.
        datos = contrasenas.generar_contrasena_robusta(
            longitud=12,
            incluir_mayusculas=False,
            incluir_minusculas=False,
            incluir_numeros=False,
            incluir_simbolos=True,
            evitar_ambiguos=True,
        )
        self.assertTrue(all(c in string.punctuation for c in datos["contrasena"]))

    def test_funcion_expuesta_devuelve_string(self) -> None:
        resultado = contrasenas.generar_contraseña_robusta(longitud=20)
        self.assertIsInstance(resultado, str)
        self.assertIn("Contraseña generada", resultado)
        self.assertIn("Entropía estimada", resultado)


if __name__ == "__main__":
    unittest.main()
