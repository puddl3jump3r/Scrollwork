"""Free online AI provider fallback using g4f (GPT4Free).

Used when Ollama is not available, providing access to free AI models
via PollinationsAI (no API key required).
"""

import json
import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

POLLINATIONS_MODELS_URL = "https://text.pollinations.ai/models"
DEFAULT_MODEL = "openai-fast"


class FreeAIProvider:
    """Fallback AI provider using free online models via g4f."""

    def __init__(self) -> None:
        self._available = False
        self._client = None
        self._provider = None
        self._current_model = DEFAULT_MODEL
        self._models: dict[str, dict[str, Any]] = {}

    async def initialize(self) -> bool:
        """Check if g4f is available and initialize the client."""
        try:
            from g4f.client import Client
            from g4f.Provider import PollinationsAI

            self._client = Client(provider=PollinationsAI)
            self._provider = PollinationsAI
            self._available = True

            # Fetch actual available models from PollinationsAI API
            await self._fetch_models()

            logger.info(
                "Free AI provider initialized (PollinationsAI) with %d models",
                len(self._models),
            )
            return True
        except ImportError:
            logger.warning("g4f not installed - free AI fallback unavailable")
            return False
        except Exception as e:
            logger.warning("Failed to initialize free AI provider: %s", e)
            return False

    async def _fetch_models(self) -> None:
        """Fetch available models from PollinationsAI API."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    POLLINATIONS_MODELS_URL, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self._models = {}
                        for m in data:
                            name = m.get("name", "")
                            if not name:
                                continue
                            self._models[name] = m
                            # Also register aliases
                            for alias in m.get("aliases", []):
                                self._models[alias] = m
                        logger.info(
                            "Fetched %d models from PollinationsAI", len(data)
                        )
                    else:
                        logger.warning(
                            "Failed to fetch models: HTTP %d", resp.status
                        )
                        self._models = {
                            DEFAULT_MODEL: {
                                "name": DEFAULT_MODEL,
                                "description": "Default free model",
                            }
                        }
        except Exception as e:
            logger.warning("Error fetching PollinationsAI models: %s", e)
            self._models = {
                DEFAULT_MODEL: {
                    "name": DEFAULT_MODEL,
                    "description": "Default free model",
                }
            }

    @property
    def is_available(self) -> bool:
        return self._available

    def list_models(self) -> list[dict[str, Any]]:
        """List available free models (unique model names only, no aliases)."""
        seen: set[str] = set()
        result = []
        for name, info in self._models.items():
            canonical = info.get("name", name)
            if canonical in seen:
                continue
            seen.add(canonical)
            desc = info.get("description", "Free model")
            result.append(
                {
                    "name": canonical,
                    "model": canonical,
                    "size": 0,
                    "provider": f"PollinationsAI (free) - {desc}",
                    "modified_at": "",
                }
            )
        return result

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

        # Resolve model name to canonical PollinationsAI name
        # This bypasses g4f's broken alias mapping
        model_info = self._models.get(model)
        if model_info:
            model_id = model_info.get("name", model)
        else:
            model_id = DEFAULT_MODEL
            logger.warning(
                "Model '%s' not found in PollinationsAI, using '%s'",
                model,
                DEFAULT_MODEL,
            )

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

        # Inject tool descriptions into the system prompt so the model
        # knows what tools are available (free providers don't support
        # the native tools parameter)
        if tools and clean_messages and clean_messages[0]["role"] == "system":
            tool_desc = self._format_tools_for_prompt(tools)
            clean_messages[0]["content"] += tool_desc

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

    @staticmethod
    def _format_tools_for_prompt(tools: list[dict[str, Any]]) -> str:
        """Format tool definitions as text to inject into the system prompt.

        Since free providers don't support the native tools parameter,
        we describe the available tools in the system prompt so the model
        knows what it can call.
        """
        lines = [
            "\n\n## AVAILABLE TOOLS",
            "You MUST use these tools by outputting a JSON block. "
            "Do NOT just describe what you would do - actually call the tool.",
            "To call a tool, output EXACTLY this format (no other text around it):\n",
            '```tool_call',
            '{"name": "tool_name", "arguments": {"arg1": "value1"}}',
            '```\n',
            "After outputting a tool call, STOP and wait for the result. "
            "Do NOT output multiple tool calls at once.\n",
            "Available tools:",
        ]
        for tool in tools:
            func = tool.get("function", {})
            name = func.get("name", "")
            desc = func.get("description", "")
            params = func.get("parameters", {})
            props = params.get("properties", {})
            required = params.get("required", [])

            param_parts = []
            for pname, pinfo in props.items():
                req = " (required)" if pname in required else " (optional)"
                param_parts.append(
                    f"    - {pname}: {pinfo.get('description', pinfo.get('type', ''))}{req}"
                )

            lines.append(f"\n### {name}")
            lines.append(f"  {desc}")
            if param_parts:
                lines.append("  Parameters:")
                lines.extend(param_parts)

        return "\n".join(lines)

    async def close(self) -> None:
        """Clean up resources."""
        self._client = None
        self._available = False
