"""Pruebas de la app web/PWA (sin abrir puertos: TestClient en memoria)."""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from core import auditoria, cambios, programador, self_coder, tareas
from interfaces import web_app
from memory import perfil

CLAVE = "clave-de-prueba-muy-larga-123"


class CerebroFalso:
    def __init__(self) -> None:
        self.visto = {}

    def ask(self, prompt, on_token=None):
        # Lo que el cerebro ve al responder a la web: sin confirmaciones y auditado como "web".
        self.visto = {"confirmar": self_coder._confirmation_allowed.get(), "origen": auditoria._origen.get()}
        for trozo in ("Hola, ", "Cristhian"):
            on_token(trozo)
        return "Hola, Cristhian", "local"


class WebTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cerebro = CerebroFalso()
        self.cliente = TestClient(web_app.crear_app(self.cerebro, clave=CLAVE))
        self.auth = {"Authorization": f"Bearer {CLAVE}"}

    def tearDown(self) -> None:
        auditoria.reanudar()

    def test_paginas_publicas_y_api_protegida(self) -> None:
        inicio = self.cliente.get("/")
        self.assertEqual(inicio.status_code, 200)
        self.assertIn("default-src 'self'", inicio.headers["content-security-policy"])
        self.assertEqual(self.cliente.get("/manifest.webmanifest").json()["display"], "standalone")
        self.assertEqual(self.cliente.get("/sw.js").status_code, 200)
        self.assertEqual(self.cliente.get("/static/icon-512.png").status_code, 200)
        self.assertEqual(self.cliente.get("/api/estado").status_code, 401)
        self.assertEqual(self.cliente.get("/api/estado", headers={"Authorization": "Bearer otra"}).status_code, 401)
        self.assertEqual(self.cliente.get("/docs").status_code, 404)        # sin documentación expuesta
        self.assertIn("estado", self.cliente.get("/api/estado", headers=self.auth).json())

    def test_bloqueo_tras_muchos_intentos(self) -> None:
        for _ in range(web_app.MAX_FALLOS):
            self.cliente.post("/api/login", headers={"Authorization": "Bearer mal"})
        # Bloqueado incluso con el token correcto, hasta que pase el tiempo.
        self.assertEqual(self.cliente.post("/api/login", headers=self.auth).status_code, 429)

    def test_chat_en_vivo_sin_confirmaciones_y_auditado(self) -> None:
        resp = self.cliente.post("/api/chat", headers=self.auth, json={"texto": "hola"})
        lineas = [json.loads(l) for l in resp.text.splitlines() if l.strip()]
        self.assertEqual([l["t"] for l in lineas if "t" in l], ["Hola, ", "Cristhian"])
        self.assertEqual(lineas[-1], {"fin": "Hola, Cristhian", "motor": "local"})
        self.assertEqual(self.cerebro.visto, {"confirmar": False, "origen": "web"})
        self.assertEqual(self.cliente.post("/api/chat", headers=self.auth, json={"texto": ""}).status_code, 422)

    def test_parar_y_reanudar(self) -> None:
        self.cliente.post("/api/parar", headers=self.auth)
        self.assertTrue(self.cliente.get("/api/estado", headers=self.auth).json()["detenido"])
        self.cliente.post("/api/reanudar", headers=self.auth)
        self.assertFalse(auditoria.detenido())

    def test_tareas_crear_y_cancelar(self) -> None:
        id_tarea = self.cliente.post("/api/tareas", headers=self.auth, json={"objetivo": "resumir noticias"}).json()["id"]
        self.assertEqual(tareas.obtener(id_tarea)["origen"], "web")
        self.assertIn(id_tarea, [t["id"] for t in self.cliente.get("/api/tareas", headers=self.auth).json()])
        self.assertEqual(self.cliente.post(f"/api/tareas/{id_tarea}/cancelar", headers=self.auth).status_code, 200)
        self.assertEqual(self.cliente.post(f"/api/tareas/{id_tarea}/cancelar", headers=self.auth).status_code, 409)
        self.assertEqual(self.cliente.post(f"/api/tareas/{id_tarea}/borrar", headers=self.auth).status_code, 404)

    def test_memoria_listar_y_olvidar(self) -> None:
        perfil.guardar("color favorito", "verde", "gustos", "prueba")
        hecho = next(h for h in self.cliente.get("/api/memoria", headers=self.auth).json() if h["valor"] == "verde")
        self.assertEqual(self.cliente.delete(f"/api/memoria/{hecho['id']}", headers=self.auth).status_code, 200)
        self.assertNotIn("verde", [h["valor"] for h in perfil.hechos()])
        self.assertEqual(self.cliente.delete(f"/api/memoria/{hecho['id']}", headers=self.auth).status_code, 404)

    def test_cambios_exigen_revision_y_confirmar_pruebas_fallidas(self) -> None:
        id_tarea = tareas.crear("programa", "añade /hora", max_intentos=1, estado="esperando_autorizacion")
        tareas._actualizar(id_tarea, datos=json.dumps({"commit": "abc", "pruebas_ok": False, "archivos": ["x.py"]}))
        with patch.object(programador, "diff", return_value="+    subprocess.run(cmd, shell=True)\n"), \
             patch.object(programador, "aprobar", return_value="f00dcafe") as aprobar:
            info = self.cliente.get(f"/api/cambios/{id_tarea}", headers=self.auth).json()
            self.assertTrue(info["puede_aplicar"])
            self.assertEqual(len(info["avisos"]), 1)
            negado = self.cliente.post(f"/api/cambios/{id_tarea}/aplicar", headers=self.auth, json={})
            self.assertEqual(negado.status_code, 409)
            aprobar.assert_not_called()
            ok = self.cliente.post(f"/api/cambios/{id_tarea}/aplicar", headers=self.auth,
                                   json={"aceptar_pruebas_fallidas": True})
            self.assertEqual(ok.json()["merge"], "f00dcafe")
        self.assertEqual(tareas.obtener(id_tarea)["estado"], "completada")
        self.assertTrue(cambios.revisar(id_tarea)["puede_deshacer"])
        self.assertEqual(self.cliente.post(f"/api/cambios/{id_tarea}/aplicar", headers=self.auth, json={}).status_code, 409)
        self.assertEqual(self.cliente.get("/api/cambios/nada", headers=self.auth).status_code, 409)

    def test_actividad_mas_reciente_primero(self) -> None:
        auditoria.registrar("prueba", "primera")
        auditoria.registrar("prueba", "segunda")
        actividad = self.cliente.get("/api/actividad?limite=2", headers=self.auth).json()
        self.assertEqual([a["nombre"] for a in actividad], ["segunda", "primera"])


if __name__ == "__main__":
    unittest.main()
