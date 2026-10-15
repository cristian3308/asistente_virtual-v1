"""Síntesis de voz Edge TTS y reproducción local con pygame."""
from __future__ import annotations

import asyncio
import re
import tempfile
import queue
import threading
from pathlib import Path


def limpiar_texto(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!\[([^]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[#>*_~|]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


async def _speak_async(text: str, output: Path) -> None:
    import edge_tts
    await edge_tts.Communicate(text, voice="es-CO-GonzaloNeural").save(str(output))


def hablar(text: str) -> None:
    clean = limpiar_texto(text)
    if not clean:
        return
    import pygame
    with tempfile.TemporaryDirectory(prefix="asistente_tts_") as temp_dir:
        audio_path = Path(temp_dir) / "respuesta.mp3"
        asyncio.run(_speak_async(clean, audio_path))
        pygame.mixer.init()
        try:
            pygame.mixer.music.load(str(audio_path))
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                pygame.time.wait(100)
        finally:
            pygame.mixer.music.stop()
            pygame.mixer.quit()


class SentenceSpeaker:
    """Reproduce frases en paralelo mientras el modelo sigue generando."""
    def __init__(self) -> None:
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._buffer = ""
        self._thread = threading.Thread(target=self._worker, name="tts-oraciones", daemon=True)
        self._thread.start()

    def _worker(self) -> None:
        while True:
            sentence = self._queue.get()
            if sentence is None:
                return
            try:
                hablar(sentence)
            except Exception:
                pass

    def feed(self, text: str) -> None:
        self._buffer += text
        parts = re.split(r"(?<=[.!?])\s+|\n+", self._buffer)
        self._buffer = parts.pop() if parts else ""
        for part in parts:
            if limpiar_texto(part):
                self._queue.put(part)

    def finish(self) -> None:
        if limpiar_texto(self._buffer):
            self._queue.put(self._buffer)
        self._buffer = ""

    def close(self) -> None:
        self.finish()
        self._queue.put(None)
