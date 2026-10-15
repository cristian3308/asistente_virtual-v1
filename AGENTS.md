# Proyecto: Asistente Virtual Profundo v1 (Windows)

- Entorno principal: Windows y PowerShell; el entorno virtual vive en `.venv`.
- Ejecuta Python y pip con `\.venv\Scripts\python.exe` y `\.venv\Scripts\pip.exe`.
- Usa `pathlib.Path` para rutas locales y mantén `.env` sin sobrescribirlo ni imprimir secretos.
- Carga la skill `arquitectura-rtx3050` antes de cambiar arquitectura, hardware o proveedores LLM.
- Toda ejecución arbitraria de PowerShell requiere confirmación; no elimines ni formatees datos.
- ChromaDB, STT y TTS corren en CPU; Ollama usa el modelo local configurado.
