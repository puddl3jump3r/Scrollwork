"""Ollama API client for model interaction."""

import json
import logging
from typing import Any, AsyncIterator

import aiohttp

logger = logging.getLogger(__name__)


class OllamaClient:
    """Async client for the Ollama REST API."""

    def __init__(self, host: str = "http://localhost:11434"):
        self.host = host.rstrip("/")
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=300)
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def list_models(self) -> list[dict[str, Any]]:
        """List all models available on the Ollama server."""
        session = await self._get_session()
        try:
            async with session.get(f"{self.host}/api/tags") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("models", [])
                logger.error("Failed to list models: %s", resp.status)
                return []
        except aiohttp.ClientError as e:
            logger.error("Connection error listing models: %s", e)
            return []

    async def show_model(self, model: str) -> dict[str, Any]:
        """Get detailed info about a specific model."""
        session = await self._get_session()
        try:
            async with session.post(
                f"{self.host}/api/show", json={"name": model}
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                return {}
        except aiohttp.ClientError as e:
            logger.error("Error showing model %s: %s", model, e)
            return {}

    async def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
        temperature: float = 0.7,
        num_ctx: int = 8192,
    ) -> dict[str, Any]:
        """Send a chat completion request (non-streaming)."""
        session = await self._get_session()
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_ctx": num_ctx,
            },
        }
        if tools:
            payload["tools"] = tools

        try:
            async with session.post(
                f"{self.host}/api/chat", json=payload
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                error_text = await resp.text()
                logger.error("Chat error %s: %s", resp.status, error_text)
                return {"message": {"role": "assistant", "content": f"Error: {error_text}"}}
        except aiohttp.ClientError as e:
            logger.error("Connection error during chat: %s", e)
            return {"message": {"role": "assistant", "content": f"Connection error: {e}"}}

    async def chat_stream(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        num_ctx: int = 8192,
    ) -> AsyncIterator[dict[str, Any]]:
        """Send a streaming chat completion request."""
        session = await self._get_session()
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": temperature,
                "num_ctx": num_ctx,
            },
        }
        if tools:
            payload["tools"] = tools

        try:
            async with session.post(
                f"{self.host}/api/chat", json=payload
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    yield {"message": {"role": "assistant", "content": f"Error: {error_text}"}}
                    return
                async for line in resp.content:
                    line = line.strip()
                    if line:
                        try:
                            yield json.loads(line)
                        except json.JSONDecodeError:
                            continue
        except aiohttp.ClientError as e:
            logger.error("Stream error: %s", e)
            yield {"message": {"role": "assistant", "content": f"Connection error: {e}"}}

    async def generate(
        self,
        model: str,
        prompt: str,
        system: str | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        """Raw text generation (non-chat)."""
        session = await self._get_session()
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": False,
        }
        if system:
            payload["system"] = system

        try:
            async with session.post(
                f"{self.host}/api/generate", json=payload
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                return {"response": f"Error: {await resp.text()}"}
        except aiohttp.ClientError as e:
            return {"response": f"Connection error: {e}"}

    async def is_available(self) -> bool:
        """Check if the Ollama server is reachable."""
        session = await self._get_session()
        try:
            async with session.get(f"{self.host}/api/tags") as resp:
                return resp.status == 200
        except aiohttp.ClientError:
            return False
