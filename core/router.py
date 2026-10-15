"""Selección de proveedor LLM y fallback cloud/local."""
from __future__ import annotations

import json
from dataclasses import dataclass

from openai import OpenAI

from config import settings


@dataclass
class Motor:
    client: OpenAI
    model: str
    name: str

    @property
    def is_local(self) -> bool:
        return self.name == "Local"


class ModelRouter:
    def __init__(self) -> None:
        self.cloud_model = settings.CLOUD_MODELS["codigo"]
        self.local_selected = False
        self.cloud = OpenAI(
            base_url=settings.CLOUD_BASE_URL,
            api_key=settings.API_KEY or "sin_key",
            default_headers={
                "User-Agent": settings.USER_AGENT,
                "x-opencode-session": settings.SESSION_ID,
            },
            timeout=60.0,
        )
        self.local = OpenAI(base_url=settings.LOCAL_BASE_URL, api_key="ollama", timeout=60.0)

    def set_model(self, code: str) -> str:
        key = code.strip().lower()
        if key == "local":
            self.local_selected = True
            self.local_model_key = ""
            return f"Modelo local seleccionado: {settings.MODEL_LOCAL}"
        if key in settings.LOCAL_MODEL_ALIASES:
            self.local_selected = True
            self.local_model_key = key
            return f"Modelo local seleccionado: {settings.LOCAL_MODEL_ALIASES[key]}"
        if key in settings.LOCAL_TURBO_MODELS:
            self.local_selected = True
            self.local_model_key = key
            return f"Modelo local turbo seleccionado: {settings.LOCAL_TURBO_MODELS[key]}"
        if key in settings.CLOUD_MODELS:
            self.local_selected = False
            self.local_model_key = ""
            self.cloud_model = settings.CLOUD_MODELS[key]
            return f"Modelo cloud seleccionado: {self.cloud_model}"
        return "Modelo no reconocido. Usa codigo, razonamiento, rapido o local."

    def candidates(self, prompt: str) -> list[Motor]:
        local_ok, cloud_ok = settings.ollama_activo(), settings.cloud_configurado()
        if self.local_selected:
            key = getattr(self, "local_model_key", "")
            model = settings.LOCAL_TURBO_MODELS.get(key, settings.LOCAL_MODEL_ALIASES.get(key, settings.MODEL_LOCAL))
            ordered = [Motor(self.local, model, "Local")]
            if cloud_ok:
                ordered.append(Motor(self.cloud, self.cloud_model, "Cloud"))
        else:
            complex_task = len(prompt) > 200 or any(
                word in prompt.lower()
                for word in ("código", "codigo", "debug", "arquitectura", "refactor", "analiza", "seguridad")
            )
            ordered = []
            if complex_task and cloud_ok:
                ordered.append(Motor(self.cloud, self.cloud_model, "Cloud"))
            if local_ok:
                ordered.append(Motor(self.local, settings.MODEL_LOCAL, "Local"))
            if cloud_ok and all(m.name != "Cloud" for m in ordered):
                ordered.append(Motor(self.cloud, self.cloud_model, "Cloud"))
        if not ordered:
            raise RuntimeError("No hay motores disponibles. Inicia Ollama o configura OPENCODE_API_KEY en .env.")
        return ordered

    @staticmethod
    def _estimate_tokens(message: dict) -> int:
        content = message.get("content") or ""
        tool_calls = message.get("tool_calls") or ""
        return max(1, (len(str(content)) + len(str(tool_calls)) + 2) // 3)

    @classmethod
    def _fit_current_tool_block(cls, block: list[dict], available: int) -> list[dict]:
        """Conserva todas las respuestas de herramientas, reduciendo su texto."""
        tools = [message for message in block[1:] if message.get("role") == "tool"]
        if not tools:
            return block
        fitted = [dict(block[0])] + [dict(message) for message in tools]
        original_lengths = [len(message.get("content") or "") for message in fitted[1:]]
        total = sum(cls._estimate_tokens(message) for message in fitted)
        while total > available and any(length > 0 for length in original_lengths):
            original_lengths = [length // 2 for length in original_lengths]
            for message, length in zip(fitted[1:], original_lengths):
                original = message.get("content") or ""
                message["content"] = original[:length]
            total = sum(cls._estimate_tokens(message) for message in fitted)
        return fitted

    @classmethod
    def _trim_local_messages(cls, messages: list[dict], budget: int) -> list[dict]:
        """Recorta por bloques válidos de conversación, sin tools huérfanos."""
        if not messages:
            return []
        system = next((message for message in messages if message.get("role") == "system"), None)
        body = [message for message in messages if message is not system]
        blocks: list[list[dict]] = []
        index = 0
        while index < len(body):
            block = [body[index]]
            if body[index].get("role") == "assistant" and body[index].get("tool_calls"):
                index += 1
                while index < len(body) and body[index].get("role") == "tool":
                    block.append(body[index])
                    index += 1
            else:
                index += 1
            blocks.append(block)
        if not blocks:
            return [system] if system else []
        last_user = max((index for index, block in enumerate(blocks) if any(item.get("role") == "user" for item in block)), default=len(blocks) - 1)
        selected_current = [blocks[last_user]]
        used = (cls._estimate_tokens(system) if system else 0) + sum(cls._estimate_tokens(item) for item in selected_current[0])
        for block in blocks[last_user + 1:]:
            cost = sum(cls._estimate_tokens(item) for item in block)
            if used + cost > budget:
                if block[0].get("role") == "assistant" and block[0].get("tool_calls"):
                    fitted = cls._fit_current_tool_block(block, max(1, budget - used))
                    selected_current.append(fitted)
                break
            selected_current.append(block)
            used += cost
        selected_history: list[list[dict]] = []
        for block in reversed(blocks[:last_user]):
            cost = sum(cls._estimate_tokens(item) for item in block)
            if used + cost > budget:
                break
            selected_history.insert(0, block)
            used += cost
        selected_blocks = selected_history + selected_current
        while selected_blocks and selected_blocks[0][0].get("role") != "user":
            selected_blocks.pop(0)
        result = [item for block in selected_blocks for item in block]
        return ([system] if system else []) + result

    @staticmethod
    def _payload_for(motor: Motor, kwargs: dict) -> dict:
        payload = dict(kwargs)
        if motor.is_local:
            messages = [dict(message) for message in payload.get("messages", [])]
            max_tokens = int(payload.get("max_tokens", 512))
            tool_tokens = max(1, len(json.dumps(payload.get("tools") or [], ensure_ascii=False)) // 3)
            context_budget = max(256, settings.OLLAMA_EXTRA_BODY["options"]["num_ctx"] - max_tokens - tool_tokens)
            payload["messages"] = ModelRouter._trim_local_messages(messages, context_budget)
            messages = payload["messages"]
            if messages and messages[-1].get("role") == "user":
                last = dict(messages[-1])
                content = last.get("content") or ""
                if motor.model.startswith("qwen3") and "/no_think" not in content:
                    last["content"] = content + "\n/no_think"
                messages[-1] = last
            payload["messages"] = messages
            extra_body = {**settings.OLLAMA_EXTRA_BODY, "options": {**settings.OLLAMA_EXTRA_BODY["options"]}}
            if motor.model.startswith("qwen3"):
                extra_body["think"] = False
            payload["extra_body"] = extra_body
            payload.setdefault("max_tokens", 512)
        return payload

    def complete(self, prompt: str, **kwargs):
        errors = []
        for motor in self.candidates(prompt):
            try:
                call_kwargs = dict(kwargs)
                if "tools" in call_kwargs:
                    from tools.registry import obtener_herramientas_relevantes
                    call_kwargs["tools"] = obtener_herramientas_relevantes(prompt, motor.is_local)
                    if call_kwargs["tools"] is None:
                        call_kwargs.pop("tool_choice", None)
                result = motor.client.chat.completions.create(model=motor.model, **self._payload_for(motor, call_kwargs))
                return result, motor
            except Exception as exc:  # fallback ante errores de red/modelo/API
                errors.append(f"{motor.name} ({motor.model}): {exc}")
        raise RuntimeError("Fallaron todos los motores: " + " | ".join(errors))

    def stream(self, prompt: str, **kwargs):
        """Devuelve `(chunk, motor)` mientras llega cada fragmento del proveedor."""
        errors = []
        for motor in self.candidates(prompt):
            try:
                call_kwargs = dict(kwargs)
                if "tools" in call_kwargs:
                    from tools.registry import obtener_herramientas_relevantes
                    call_kwargs["tools"] = obtener_herramientas_relevantes(prompt, motor.is_local)
                    if call_kwargs["tools"] is None:
                        call_kwargs.pop("tool_choice", None)
                stream = motor.client.chat.completions.create(
                    model=motor.model, stream=True, **self._payload_for(motor, call_kwargs)
                )
                for chunk in stream:
                    yield chunk, motor
                return
            except Exception as exc:
                errors.append(f"{motor.name} ({motor.model}): {exc}")
        raise RuntimeError("Fallaron todos los motores en streaming: " + " | ".join(errors))
