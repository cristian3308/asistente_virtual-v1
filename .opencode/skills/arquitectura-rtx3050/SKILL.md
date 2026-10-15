---
name: arquitectura-rtx3050
description: Reglas del hardware RTX 3050 4GB, Windows PowerShell y OpenCode Go para este proyecto.
---
# Entorno de Cristhian (Windows + Híbrido)

1. Windows 11 con PowerShell. Evita comandos exclusivos de Linux. Ejecuta Python y pip con `\.venv\Scripts\python.exe` y `\.venv\Scripts\pip.exe`; en Python usa `pathlib.Path`.
2. Hardware: Intel i5-12500H, 24 GB RAM, RTX 3050 Laptop 4 GB e Intel Iris Xe. Ollama usa `qwen3:4b`; ChromaDB, embeddings y STT se mantienen en CPU (`device="cpu"`, `compute_type="int8"`).
3. OpenCode Go: `https://opencode.ai/zen/go/v1`; modelos configurables `kimi-k2.7-code`, `qwen3.7-plus`, `glm-5.3`. Incluye `User-Agent: cristhian-assistant/1.0` y `x-opencode-session`.
4. Ollama OpenAI-compatible: `http://127.0.0.1:11434/v1`, modelo `qwen3:4b`. Comprueba el puerto 11434 mediante socket con timeout de 0.2 s.
5. Pide confirmación antes de ejecutar comandos de PowerShell no incluidos en la lista de solo lectura y bloquea los destructivos.
