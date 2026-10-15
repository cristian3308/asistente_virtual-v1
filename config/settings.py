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


def ollama_activo() -> bool:
    """Comprueba si Ollama acepta conexiones en localhost:11434 (máximo 200 ms)."""
    try:
        with socket.create_connection(("127.0.0.1", 11434), timeout=0.2):
            return True
    except OSError:
        return False


def cloud_configurado() -> bool:
    return bool(API_KEY and API_KEY != "tu_api_key_real_de_opencode_aqui")


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
