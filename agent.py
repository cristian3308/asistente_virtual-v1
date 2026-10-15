"""Compatibilidad con el punto de entrada anterior; usa ahora `python main.py`."""
from config.settings import API_KEY as OPENCODE_API_KEY, MODEL_LOCAL as MODELO_LOCAL, ollama_activo as ollama_esta_activo
from core.brain import AssistantBrain
from tools.system_tools import estado_hardware, explorar_directorio, listar_procesos_pesados

brain = AssistantBrain()


def preguntar_al_asistente(prompt_usuario: str) -> str:
    respuesta, _motor = brain.ask(prompt_usuario)
    return respuesta


if __name__ == "__main__":
    from main import main
    main()
