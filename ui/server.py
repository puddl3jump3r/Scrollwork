"""FastAPI server with WebSocket chat interface."""

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger(__name__)

# Will be set by main.py
agent = None  # type: ignore

app = FastAPI(title="Nexus Agent", version="1.0.0")

# Serve static files
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    """Serve the main chat interface."""
    index_path = STATIC_DIR / "index.html"
    return HTMLResponse(content=index_path.read_text())


@app.get("/api/status")
async def get_status() -> JSONResponse:
    """Get agent status."""
    if agent is None:
        return JSONResponse({"error": "Agent not initialized"}, status_code=503)
    return JSONResponse(agent.get_status())


@app.get("/api/models")
async def list_models() -> JSONResponse:
    """List available Ollama models."""
    if agent is None:
        return JSONResponse({"error": "Agent not initialized"}, status_code=503)
    models = agent.model_selector.list_available()
    return JSONResponse({"models": models, "current": agent.current_model})


@app.post("/api/model")
async def switch_model(body: dict[str, Any]) -> JSONResponse:
    """Switch the active model."""
    if agent is None:
        return JSONResponse({"error": "Agent not initialized"}, status_code=503)
    model_name = body.get("model")
    if not model_name:
        return JSONResponse({"error": "No model specified"}, status_code=400)
    agent.current_model = model_name
    return JSONResponse({"success": True, "model": model_name})


@app.get("/api/memory/stats")
async def memory_stats() -> JSONResponse:
    """Get memory statistics."""
    if agent is None:
        return JSONResponse({"error": "Agent not initialized"}, status_code=503)
    stats = await agent.memory.get_stats()
    return JSONResponse(stats)


@app.get("/api/mcp/status")
async def mcp_status() -> JSONResponse:
    """Get MCP server status."""
    if agent is None:
        return JSONResponse({"error": "Agent not initialized"}, status_code=503)
    return JSONResponse(agent.mcp_manager.get_status())


@app.post("/api/mcp/reload")
async def mcp_reload() -> JSONResponse:
    """Reload MCP configuration."""
    if agent is None:
        return JSONResponse({"error": "Agent not initialized"}, status_code=503)
    results = await agent.mcp_manager.reload_config()
    return JSONResponse({"results": results})


@app.get("/api/database/schema")
async def database_schema() -> JSONResponse:
    """Get the database schema."""
    if agent is None:
        return JSONResponse({"error": "Agent not initialized"}, status_code=503)
    schema = await agent.database.get_full_schema()
    tables = await agent.database.list_tables()
    return JSONResponse({"schema_text": schema, "tables": tables})


class ConnectionManager:
    """Manages WebSocket connections."""

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self.active_connections.remove(websocket)

    async def send_json(self, websocket: WebSocket, data: dict[str, Any]) -> None:
        try:
            await websocket.send_json(data)
        except Exception:
            pass


ws_manager = ConnectionManager()


@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time chat."""
    await ws_manager.connect(websocket)
    logger.info("Client connected via WebSocket")

    try:
        while True:
            # Receive message from client
            data = await websocket.receive_json()
            message = data.get("message", "")
            mode = data.get("mode", "chat")

            if not message:
                await ws_manager.send_json(websocket, {
                    "type": "error",
                    "content": "Empty message",
                })
                continue

            if agent is None:
                await ws_manager.send_json(websocket, {
                    "type": "error",
                    "content": "Agent not initialized",
                })
                continue

            # Send acknowledgment
            await ws_manager.send_json(websocket, {
                "type": "ack",
                "content": "Processing...",
                "mode": mode,
            })

            # Stream callback to send updates to the client
            async def stream_callback(
                event_type: str, content: str, metadata: Any
            ) -> None:
                await ws_manager.send_json(websocket, {
                    "type": event_type,
                    "content": content,
                    "metadata": metadata if isinstance(metadata, dict) else {},
                })

            try:
                # Process the message
                result = await agent.process_message(
                    message, mode=mode, stream_callback=stream_callback
                )

                # Send final response
                await ws_manager.send_json(websocket, {
                    "type": "final_response",
                    "content": result.get("response", ""),
                    "model": result.get("model", ""),
                    "reasoning": result.get("reasoning", {}),
                    "plan": result.get("plan"),
                })

            except Exception as e:
                logger.error("Error processing message: %s", e, exc_info=True)
                await ws_manager.send_json(websocket, {
                    "type": "error",
                    "content": f"Error: {str(e)}",
                })

    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
        logger.info("Client disconnected")
    except Exception as e:
        logger.error("WebSocket error: %s", e)
        ws_manager.disconnect(websocket)
