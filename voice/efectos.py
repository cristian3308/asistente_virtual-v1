"""Toques de JARVIS: sonidos cortos y frases instantáneas mientras piensa.

- sonido("escucha" | "listo" | "aviso"): tonos suaves generados aquí mismo (sin archivos).
- frase_de_espera(): ruta de un audio ya grabado ("Enseguida.", "Un momento.") con la voz
  elegida. Se graban una vez en data/voz_cache/<voz>/ y suenan en ~0,1 s, así no hay
  silencio mientras el modelo piensa.
"""
from __future__ import annotations

import hashlib
import random
import threading
from pathlib import Path

from config import settings

CACHE = settings.DATA_DIR / "voz_cache"
FRASES_DE_ESPERA = ("Enseguida.", "Un momento.", "Déjame revisar.", "Claro, dame un segundo.", "Ahora mismo.")
TONOS = {
    # nombre: [(frecuencia Hz, duración s), ...]
    "escucha": [(660, 0.07), (880, 0.09)],    # sube: "te escucho"
    "listo": [(880, 0.07), (660, 0.10)],      # baja: "terminé de escuchar"
    "aviso": [(740, 0.08), (740, 0.08)],
}
VOLUMEN = 0.18
_lock = threading.Lock()


def _onda(tonos, sample_rate: int):
    import numpy as np

    partes = []
    for frecuencia, duracion in tonos:
        t = np.arange(int(sample_rate * duracion)) / sample_rate
        onda = np.sin(2 * np.pi * frecuencia * t) * VOLUMEN
        borde = min(len(t) // 4, int(0.012 * sample_rate))
        envolvente = np.ones_like(t)
        envolvente[:borde] = np.linspace(0, 1, borde)
        envolvente[-borde:] = np.linspace(1, 0, borde)     # sin "clics" al empezar y terminar
        partes.append(onda * envolvente)
    return np.concatenate(partes)


def sonido(nombre: str, esperar: bool = False) -> None:
    """Reproduce un tono corto. Nunca lanza: un sonido no debe romper nada."""
    try:
        import numpy as np
        import pygame

        if not pygame.mixer.get_init():
            pygame.mixer.init()
        frecuencia, _formato, canales = pygame.mixer.get_init()
        muestras = (_onda(TONOS[nombre], frecuencia) * 32767).astype(np.int16)
        if canales == 2:
            muestras = np.column_stack([muestras, muestras])
        tono = pygame.sndarray.make_sound(np.ascontiguousarray(muestras))
        canal = tono.play()
        if esperar:
            while canal is not None and canal.get_busy():
                pygame.time.wait(10)
    except Exception:
        pass


def _ruta(frase: str, voz: str) -> Path:
    """La grabación depende de la voz real (id, velocidad y tono): si cambia, se vuelve a grabar."""
    from voice import mouth_tts
    parametros = "|".join(mouth_tts._parametros_voz(voz))
    clave = hashlib.sha1(f"{frase}|{parametros}".encode("utf-8")).hexdigest()[:12]
    return CACHE / voz / f"{clave}.mp3"


def precargar_frases() -> None:
    """Graba en segundo plano las frases de espera de la voz actual (solo las que falten)."""
    def grabar() -> None:
        import asyncio
        from voice import mouth_tts
        voz = mouth_tts.voz_actual()
        for frase in FRASES_DE_ESPERA:
            destino = _ruta(frase, voz)
            if destino.exists():
                continue
            try:
                destino.parent.mkdir(parents=True, exist_ok=True)
                temporal = destino.with_suffix(".tmp.mp3")
                asyncio.run(mouth_tts._speak_async(frase, temporal, voz))
                temporal.replace(destino)
            except Exception:
                continue
    threading.Thread(target=grabar, name="voz-frases-espera", daemon=True).start()


def frase_de_espera() -> Path | None:
    """Una frase de espera ya grabada con la voz actual, o None si aún no hay."""
    from voice import mouth_tts
    voz = mouth_tts.voz_actual()
    listas = [r for r in (_ruta(f, voz) for f in FRASES_DE_ESPERA) if r.exists()]
    return random.choice(listas) if listas else None
