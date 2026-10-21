"""Notificaciones push al celular (Web Push), aunque la app esté cerrada.

El PC firma cada aviso con su propia clave (VAPID, en data/push_vapid.json) y lo cifra
para tu celular; el servicio de push del navegador (en Android, el de Google) solo
transporta un sobre cifrado que no puede leer. El celular se suscribe desde la app web,
que debe estar abierta por HTTPS (tailscale serve), como exigen los navegadores.
"""
from __future__ import annotations

import base64
import json
import threading

from config import settings

CLAVES = settings.DATA_DIR / "push_vapid.json"
SUSCRIPCIONES = settings.DATA_DIR / "push_suscripciones.json"
CONTACTO = "mailto:asistente@localhost"   # los servicios de push exigen un contacto; no se usa para nada más
_lock = threading.Lock()


def _claves() -> dict:
    """Crea el par de claves la primera vez; después siempre usa el mismo."""
    with _lock:
        if CLAVES.exists():
            return json.loads(CLAVES.read_text(encoding="utf-8"))
        from cryptography.hazmat.primitives import serialization
        from py_vapid import Vapid01
        vapid = Vapid01()
        vapid.generate_keys()
        privada = vapid.private_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                  serialization.NoEncryption()).decode()
        publica = vapid.public_key.public_bytes(serialization.Encoding.X962,
                                                serialization.PublicFormat.UncompressedPoint)
        datos = {"privada_pem": privada,
                 "publica": base64.urlsafe_b64encode(publica).decode().rstrip("=")}
        CLAVES.parent.mkdir(parents=True, exist_ok=True)
        CLAVES.write_text(json.dumps(datos), encoding="utf-8")
        return datos


def clave_publica() -> str:
    return _claves()["publica"]


def _suscripciones() -> list[dict]:
    try:
        return json.loads(SUSCRIPCIONES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _guardar(lista: list[dict]) -> None:
    SUSCRIPCIONES.parent.mkdir(parents=True, exist_ok=True)
    SUSCRIPCIONES.write_text(json.dumps(lista, indent=1), encoding="utf-8")


def suscribir(suscripcion: dict) -> int:
    """Guarda la suscripción de un dispositivo (sin duplicados). Devuelve cuántas hay."""
    if not isinstance(suscripcion, dict) or not str(suscripcion.get("endpoint", "")).startswith("https://"):
        raise ValueError("Suscripción no válida.")
    claves = suscripcion.get("keys") or {}
    if not claves.get("p256dh") or not claves.get("auth"):
        raise ValueError("A la suscripción le faltan sus claves.")
    with _lock:
        lista = [s for s in _suscripciones() if s.get("endpoint") != suscripcion["endpoint"]]
        lista.append({"endpoint": suscripcion["endpoint"], "keys": {"p256dh": claves["p256dh"], "auth": claves["auth"]}})
        _guardar(lista)
        return len(lista)


def hay_suscripciones() -> bool:
    return bool(_suscripciones())


def enviar(cuerpo: str, titulo: str = "Jarvis", url: str = "/") -> int:
    """Envía el aviso a todos los dispositivos suscritos; borra los que ya no existen. Devuelve cuántos llegaron."""
    lista = _suscripciones()
    if not lista:
        return 0
    from pywebpush import WebPushException, webpush
    datos = json.dumps({"titulo": titulo, "cuerpo": (cuerpo or "")[:300], "url": url}, ensure_ascii=False)
    privada = _claves()["privada_pem"]
    entregados, vigentes = 0, []
    for suscripcion in lista:
        try:
            webpush(subscription_info=suscripcion, data=datos, vapid_private_key=privada,
                    vapid_claims={"sub": CONTACTO}, ttl=3600, timeout=10)
            entregados += 1
            vigentes.append(suscripcion)
        except WebPushException as exc:
            codigo = getattr(getattr(exc, "response", None), "status_code", None)
            if codigo not in (404, 410):     # 404/410: el celular canceló la suscripción
                vigentes.append(suscripcion)
        except Exception:
            vigentes.append(suscripcion)
    if len(vigentes) != len(lista):
        with _lock:
            _guardar(vigentes)
    return entregados


def enviar_en_segundo_plano(cuerpo: str, titulo: str = "Jarvis") -> None:
    if hay_suscripciones():
        threading.Thread(target=enviar, args=(cuerpo, titulo), name="push", daemon=True).start()
