"""Free online AI provider fallback using g4f (GPT4Free).

Used when Ollama is not available, providing access to free AI models
via PollinationsAI (no API key required).
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Model mapping: friendly name -> g4f model identifier
FREE_MODELS = {
    "gpt-4o-mini": "gpt-4o-mini",
    "openai": "openai",
    "claude-hybridspace": "claude-hybridspace",
    "deepseek-r1": "deepseek-r1",
    "qwen-2.5-coder-32b": "qwen-2.5-coder-32b",
    "llama-3.3-70b": "llama-3.3-70b",
    "mistral-small": "mistral-small",
}

DEFAULT_MODEL = "openai"


class FreeAIProvider:
    """Fallback AI provider using free online models via g4f."""

    def __init__(self) -> None:
        self._available = False
        self._client = None
        self._provider = None
        self._current_model = DEFAULT_MODEL

    async def initialize(self) -> bool:
        """Check if g4f is available and initialize the client."""
        try:
            from g4f.client import Client
            from g4f.Provider import PollinationsAI

            self._client = Client(provider=PollinationsAI)
            self._provider = PollinationsAI
            self._available = True
            logger.info("Free AI provider initialized (PollinationsAI)")
            return True
        except ImportError:
            logger.warning("g4f not installed - free AI fallback unavailable")
            return False
        except Exception as e:
            logger.warning("Failed to initialize free AI provider: %s", e)
            return False

    @property
    def is_available(self) -> bool:
        return self._available

    def list_models(self) -> list[dict[str, Any]]:
        """List available free models."""
        return [
            {
                "name": name,
                "model": model_id,
                "size": 0,
                "provider": "PollinationsAI (free)",
                "modified_at": "",
            }
            for name, model_id in FREE_MODELS.items()
        ]

    async def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
    ) -> dict[str, Any]:
        """Send a chat completion request to the free provider.

        Returns response in Ollama-compatible format.
        """
        if not self._available or self._client is None:
            return {
                "message": {
                    "role": "assistant",
                    "content": "Free AI provider not available.",
                }
            }

        # Map model name to g4f model id
        model_id = FREE_MODELS.get(model, model)

        # Clean messages - g4f expects simple role/content dicts
        clean_messages = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "tool":
                # Convert tool results to user messages for compatibility
                clean_messages.append({
                    "role": "user",
                    "content": f"[Tool Result]: {content}",
                })
            else:
                clean_messages.append({"role": role, "content": content})

        try:
            response = self._client.chat.completions.create(
                model=model_id,
                messages=clean_messages,
            )

            content = response.choices[0].message.content
            return {
                "message": {
                    "role": "assistant",
                    "content": content,
                }
            }
        except Exception as e:
            logger.error("Free AI chat error: %s", e)
            return {
                "message": {
                    "role": "assistant",
                    "content": f"Error from free AI provider: {e}",
                }
            }

    async def close(self) -> None:
        """Clean up resources."""
        self._client = None
        self._available = False
