"""Configuración central del asistente híbrido para Windows."""
from __future__ import annotations

import os
import socket
import uuid
import ipaddress
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env")

DATA_DIR = ROOT_DIR / "data"
DB_PATH = DATA_DIR / "memoria_sesiones.db"
CHROMA_PATH = DATA_DIR / "chroma_db"
VAULT_PATH = Path(os.getenv("OBSIDIAN_VAULT_PATH", str(DATA_DIR / "boveda_notas"))).expanduser()
_configured_read_roots = [value for value in os.getenv("ASSISTANT_ALLOWED_READ_ROOTS", "").split(os.pathsep) if value.strip()]
ALLOWED_READ_ROOTS = tuple(
    Path(value).expanduser().resolve()
    for value in (_configured_read_roots or [str(ROOT_DIR), str(VAULT_PATH)])
)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_ALLOWED_USER_ID = os.getenv("TELEGRAM_ALLOWED_USER_ID", "").strip()
SESSION_ID = str(uuid.uuid4())
API_KEY = os.getenv("OPENCODE_API_KEY", "").strip().strip('"').strip("'")
CLOUD_BASE_URL = "https://opencode.ai/zen/go/v1"
LOCAL_BASE_URL = "http://127.0.0.1:11434/v1"
CLOUD_MODELS = {
    # IDs exactos de OpenCode Go con soporte de chat + herramientas (verificado 2026-10-17).
    # Los modelos "*-luna" responden ModelProtocolUnsupported en /chat/completions.
    "codigo": "kimi-k2.7-code",
    "razonamiento": "qwen3.7-plus",
    "rapido": "glm-5.3",
}
MODEL_LOCAL = "qwen2.5-coder:3b"
LOCAL_MODEL_ALIASES = {
    "local": MODEL_LOCAL,
    "qwen4": "qwen3:4b",
    "qwen3:4b": "qwen3:4b",
}
LOCAL_TURBO_MODELS = {"turbo": "qwen3:1.7b", "turbo3": "llama3.2:3b"}
OLLAMA_EXTRA_BODY = {
    "options": {"num_ctx": 2048, "num_batch": 512, "num_gpu": 99},
    "keep_alive": "24h",
}
USER_AGENT = "cristhian-assistant/1.0"
# Nombre del dueño: base de la memoria personal (se puede corregir diciendo "me llamo …").
USER_NAME = os.getenv("ASSISTANT_USER_NAME", "Cristhian").strip() or "Cristhian"
# Modelos para programar habilidades, en orden. minimax-m3 tardó 9 s frente a 87 s de
# kimi con el mismo resultado (pruebas 4/4) en la medición del 2026-10-17.
FORGE_MODELS = [m.strip() for m in os.getenv("ASSISTANT_FORGE_MODELS", "minimax-m3,kimi-k2.7-code").split(",") if m.strip()]
# Si el modelo local no puede resolver un turno, se repite automáticamente en la nube.
AUTO_ESCALATE = os.getenv("ASSISTANT_AUTO_ESCALATE", "1").strip().lower() not in {"0", "false", "no"}
# Personalidad JARVIS: cómo te llama y si te saluda al volver al PC tras un rato fuera.
TRATO = os.getenv(
    "ASSISTANT_TRATO",
    f"Llama al usuario {USER_NAME} y, de vez en cuando, 'señor'.",
).strip()
SALUDO_AL_VOLVER = os.getenv("ASSISTANT_SALUDO", "1").strip().lower() not in {"0", "false", "no"}
SALUDO_TRAS_MINUTOS = float(os.getenv("ASSISTANT_SALUDO_MINUTOS", "20"))
# Avatar flotante (robot-heads) al arrancar; se abre/cierra con /avatar.
AVATAR = os.getenv("ASSISTANT_AVATAR", "1").strip().lower() not in {"0", "false", "no"}
# Modelo de Faster-Whisper en CPU. Medición 2026-10-17 (voz + ruido, con pista y 8 hilos):
# "small" 15,9 % de error en 3,4 s por frase; "base" 33,6 % en 1,3 s.
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small").strip() or "small"
WHISPER_THREADS = int(os.getenv("WHISPER_THREADS", "8"))
# Palabras que Whisper suele escribir mal: van como "hotwords" (prioridad) y dentro de una frase
# de ejemplo. Medición 2026-10-19 (48 frases con ruido): dárselas como lista con comas daba 11,4 %
# de error (Whisper imitaba las comas: "Arespotifa, Ponmúsica"); como frase + hotwords, 4,7 %.
WHISPER_VOCABULARIO = os.getenv(
    "WHISPER_VOCABULARIO",
    "Jarvis Cristhian Spotify Obsidian Ollama Copilot Discord Telegram WhatsApp PowerShell Python",
)
WHISPER_PISTA = os.getenv(
    "WHISPER_PISTA",
    "Hola Jarvis, soy Cristhian. Abre Spotify, crea una nota en Obsidian, mándame un mensaje por Telegram "
    "o WhatsApp y revisa el código en Python, PowerShell o Visual Studio Code.",
)
WHISPER_BEAM = int(os.getenv("WHISPER_BEAM", "5"))
# Escucha: termina tras este silencio (s) cuando ya hablaste; deja de esperar si no empiezas.
VOZ_SILENCIO_FIN = float(os.getenv("ASSISTANT_SILENCIO_FIN", "4.0"))
VOZ_ESPERA_INICIO = float(os.getenv("ASSISTANT_ESPERA_INICIO", "8.0"))
VOZ_MAXIMO = float(os.getenv("ASSISTANT_VOZ_MAXIMO", "60"))
# App web/PWA (celular). Por defecto solo escucha en este PC; para el celular usa
# `tailscale serve` (HTTPS privado) en vez de abrirla a la red. El token, si no está
# en .env, se genera en data/web_token.txt.
# Memoria de largo plazo Hindsight (servidor aparte en .venv-hindsight, Python 3.12, con Ollama).
HINDSIGHT = os.getenv("ASSISTANT_HINDSIGHT", "1").strip().lower() not in {"0", "false", "no"}
HINDSIGHT_PUERTO = int(os.getenv("ASSISTANT_HINDSIGHT_PUERTO", "8890"))
HINDSIGHT_MODELO = os.getenv("ASSISTANT_HINDSIGHT_MODELO", "").strip()   # vacío = el modelo local del asistente
HINDSIGHT_BANCO = os.getenv("ASSISTANT_HINDSIGHT_BANCO", "cristhian").strip() or "cristhian"
WEB = os.getenv("ASSISTANT_WEB", "1").strip().lower() not in {"0", "false", "no"}
WEB_HOST = os.getenv("ASSISTANT_WEB_HOST", "127.0.0.1").strip() or "127.0.0.1"
WEB_PORT = int(os.getenv("ASSISTANT_WEB_PORT", "8780"))  # el 8765 es del avatar
WEB_TOKEN = os.getenv("ASSISTANT_WEB_TOKEN", "").strip()


def ollama_activo() -> bool:
    """Comprueba si Ollama acepta conexiones en localhost:11434 (máximo 200 ms)."""
    try:
        with socket.create_connection(("127.0.0.1", 11434), timeout=0.2):
            return True
    except OSError:
        return False


def cloud_configurado() -> bool:
    return bool(API_KEY and API_KEY != "tu_api_key_real_de_opencode_aqui")


def resolver_ruta(ruta: str | Path) -> Path:
    """Rutas relativas ("tools/x.py") se interpretan desde la carpeta del proyecto, no desde donde se arrancó."""
    destino = Path(ruta).expanduser()
    return (destino if destino.is_absolute() else ROOT_DIR / destino).resolve()


def path_is_allowed(path: Path) -> bool:
    """Evita que las herramientas locales salgan de las carpetas autorizadas."""
    resolved = path.expanduser().resolve()
    data_dir = DATA_DIR.resolve()
    if resolved == data_dir or data_dir in resolved.parents:
        return False
    if resolved.suffix.lower() in {".db", ".sqlite", ".sqlite3"}:
        return False
    return any(resolved == root or root in resolved.parents for root in ALLOWED_READ_ROOTS)


def host_is_public(host: str) -> bool:
    """Bloquea destinos locales para evitar SSRF desde la herramienta web."""
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except OSError:
        return False
    return all(
        (parsed := ipaddress.ip_address(address)).is_global
        for address in addresses
    )
