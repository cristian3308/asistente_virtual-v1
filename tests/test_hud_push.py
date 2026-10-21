"""HUD del avatar (subtítulos, eventos en vivo, telemetría) y notificaciones push al celular."""
from __future__ import annotations

import http.client
import json
import shutil
import tempfile
import threading
import unittest
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from core import estado, telemetria
from interfaces import avatar, notificaciones, push, web_app
from voice import mouth_tts


class HudTests(unittest.TestCase):
    def tearDown(self) -> None:
        estado.subtitulo("")
        while estado._voz_activa:
            estado.voz(False)

    def test_subtitulo_solo_mientras_habla(self) -> None:
        estado.subtitulo("Hecho, señor.")
        estado.publicar("idle")
        self.assertEqual(estado.actual()["subtitulo"], "")
        estado.voz(True)
        self.assertEqual(estado.actual()["subtitulo"], "Hecho, señor.")

    def test_cada_frase_se_muestra_al_decirla(self) -> None:
        vistos = []
        with patch.object(estado, "subtitulo", side_effect=vistos.append), \
             patch.object(mouth_tts, "_reproducir"), patch.object(mouth_tts.shutil, "rmtree"):
            hablante = mouth_tts.SentenceSpeaker(sintetizar=lambda t: Path(t))
            hablante.feed("Primera frase. Segunda frase. ")
            hablante.close()
        self.assertEqual(vistos, ["Primera frase.", "Segunda frase.", ""])

    def test_telemetria_sin_gpu(self) -> None:
        with patch.object(telemetria, "_gpu", return_value=None):
            datos = telemetria.medir()
        self.assertIsNone(datos["gpu"])
        self.assertTrue(0 <= datos["ram"] <= 100)

    def test_eventos_en_vivo_por_sse(self) -> None:
        servidor = avatar._Servidor(("127.0.0.1", 0), partial(avatar._Handler, directory=str(avatar.DIST_DIR)))
        threading.Thread(target=servidor.serve_forever, daemon=True).start()
        try:
            with patch.object(telemetria, "actual", return_value={"cpu": 10, "ram": 50, "gpu": 30}):
                conexion = http.client.HTTPConnection("127.0.0.1", servidor.server_address[1], timeout=5)
                conexion.request("GET", "/eventos")
                respuesta = conexion.getresponse()
                self.assertEqual(respuesta.getheader("Content-Type"), "text/event-stream; charset=utf-8")
                primero = json.loads(respuesta.readline().decode().removeprefix("data: "))
                self.assertEqual(primero["telemetria"]["ram"], 50)
                estado.publicar("searching", detalle="Revisando la red…")
                for _ in range(20):
                    linea = respuesta.readline().decode()
                    if linea.startswith("data: ") and "Revisando la red" in linea:
                        break
                else:
                    self.fail("no llegó el cambio de estado")
                conexion.close()
        finally:
            estado.publicar("idle")
            servidor.shutdown()
            servidor.server_close()


class PushTests(unittest.TestCase):
    SUSCRIPCION = {"endpoint": "https://fcm.googleapis.com/fcm/send/abc", "keys": {"p256dh": "x" * 20, "auth": "y" * 10}}

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="push_"))
        self.parches = [patch.object(push, "CLAVES", self.tmp / "vapid.json"),
                        patch.object(push, "SUSCRIPCIONES", self.tmp / "subs.json")]
        for p in self.parches:
            p.start()

    def tearDown(self) -> None:
        for p in self.parches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_suscribir_valida_y_no_duplica(self) -> None:
        self.assertEqual(push.suscribir(self.SUSCRIPCION), 1)
        self.assertEqual(push.suscribir(self.SUSCRIPCION), 1)
        with self.assertRaises(ValueError):
            push.suscribir({"endpoint": "http://inseguro"})

    def test_enviar_y_olvidar_celulares_que_cancelaron(self) -> None:
        from pywebpush import WebPushException
        push.suscribir(self.SUSCRIPCION)
        otra = {**self.SUSCRIPCION, "endpoint": "https://fcm.googleapis.com/fcm/send/vieja"}
        push.suscribir(otra)

        def webpush(subscription_info, **kwargs):
            if subscription_info["endpoint"].endswith("vieja"):
                raise WebPushException("gone", response=SimpleNamespace(status_code=410))
            self.assertIn("Tarea lista", kwargs["data"])

        with patch("pywebpush.webpush", side_effect=webpush):
            self.assertEqual(push.enviar("Tarea lista"), 1)
        self.assertEqual([s["endpoint"] for s in push._suscripciones()], [self.SUSCRIPCION["endpoint"]])

    def test_notificar_tambien_avisa_al_celular(self) -> None:
        with patch.object(push, "enviar_en_segundo_plano") as enviar, \
             patch.object(notificaciones, "enviar_telegram"), redirect_consola():
            notificaciones.notificar("Recordatorio: llamar a mamá")
        enviar.assert_called_once_with("Recordatorio: llamar a mamá")

    def test_api_de_la_app(self) -> None:
        cliente = TestClient(web_app.crear_app(None, clave="clave-de-prueba-muy-larga-123"))
        auth = {"Authorization": "Bearer clave-de-prueba-muy-larga-123"}
        self.assertEqual(len(cliente.get("/api/push/clave", headers=auth).json()["clave"]), 87)
        self.assertEqual(cliente.post("/api/push/probar", headers=auth).status_code, 409)
        self.assertEqual(cliente.post("/api/push/suscribir", headers=auth, json={"endpoint": "x"}).status_code, 400)
        self.assertEqual(cliente.post("/api/push/suscribir", headers=auth, json=self.SUSCRIPCION).json()["dispositivos"], 1)
        self.assertEqual(cliente.get("/api/push/clave").status_code, 401)


def redirect_consola():
    import contextlib
    import io
    return contextlib.redirect_stdout(io.StringIO())


if __name__ == "__main__":
    unittest.main()
