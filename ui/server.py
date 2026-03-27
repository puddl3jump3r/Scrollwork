"""FastAPI server with WebSocket chat interface and multi-user auth."""

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger(__name__)

# Will be set by main.py
agent_manager = None  # type: ignore

app = FastAPI(title="Nexus Agent", version="1.1.0")

# Serve static files
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# --- Helper: extract user from auth token ---

async def _get_user_from_token(token: str | None) -> dict[str, Any] | None:
    """Validate an auth token and return user info."""
    if not token or agent_manager is None:
        return None
    return await agent_manager.user_manager.validate_token(token)


async def _get_user_agent(username: str) -> Any:
    """Get the agent instance for a user."""
    if agent_manager is None:
        return None
    return await agent_manager.get_agent(username)


def _extract_token(request: Request) -> str | None:
    """Extract auth token from Authorization header or query param."""
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return request.query_params.get("token")


async def _require_auth(request: Request) -> tuple[dict[str, Any] | None, JSONResponse | None]:
    """Extract and validate auth. Returns (user, error_response)."""
    token = _extract_token(request)
    user = await _get_user_from_token(token)
    if not user:
        return None, JSONResponse({"error": "Not authenticated"}, status_code=401)
    return user, None


# --- Pages ---

@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    """Serve the main chat interface."""
    index_path = STATIC_DIR / "index.html"
    return HTMLResponse(content=index_path.read_text())


# --- Auth API ---

@app.post("/api/auth/register")
async def register(body: dict[str, Any]) -> JSONResponse:
    """Register a new user."""
    if agent_manager is None:
        return JSONResponse({"success": False, "error": "Server not initialized"}, status_code=503)

    username = body.get("username", "")
    password = body.get("password", "")
    display_name = body.get("display_name")

    result = await agent_manager.user_manager.register(
        username=username, password=password, display_name=display_name
    )

    if not result["success"]:
        return JSONResponse(result, status_code=400)

    # Auto-login after registration
    login_result = await agent_manager.user_manager.login(username, password)
    return JSONResponse(login_result)


@app.post("/api/auth/login")
async def login(body: dict[str, Any]) -> JSONResponse:
    """Log in a user."""
    if agent_manager is None:
        return JSONResponse({"success": False, "error": "Server not initialized"}, status_code=503)

    username = body.get("username", "")
    password = body.get("password", "")

    result = await agent_manager.user_manager.login(username, password)
    if not result["success"]:
        return JSONResponse(result, status_code=401)
    return JSONResponse(result)


@app.post("/api/auth/logout")
async def logout(request: Request) -> JSONResponse:
    """Log out the current user."""
    token = _extract_token(request)
    if token and agent_manager:
        user = await _get_user_from_token(token)
        if user:
            await agent_manager.remove_agent(user["username"])
        await agent_manager.user_manager.logout(token)
    return JSONResponse({"success": True})


@app.get("/api/auth/me")
async def get_current_user(request: Request) -> JSONResponse:
    """Get the currently logged-in user."""
    token = _extract_token(request)
    user = await _get_user_from_token(token)
    if not user:
        return JSONResponse({"authenticated": False}, status_code=401)
    return JSONResponse({"authenticated": True, "user": user})


# --- Agent API (all require auth) ---

@app.get("/api/status")
async def get_status(request: Request) -> JSONResponse:
    """Get agent status."""
    user, err = await _require_auth(request)
    if err:
        return err
    agent = await _get_user_agent(user["username"])  # type: ignore[index]
    if agent is None:
        return JSONResponse({"error": "Agent not initialized"}, status_code=503)
    status = agent.get_status()
    status["user"] = user
    return JSONResponse(status)


@app.get("/api/models")
async def list_models(request: Request) -> JSONResponse:
    """List available models."""
    user, err = await _require_auth(request)
    if err:
        return err
    agent = await _get_user_agent(user["username"])  # type: ignore[index]
    if agent is None:
        return JSONResponse({"error": "Agent not initialized"}, status_code=503)
    models = agent.model_selector.list_available()
    return JSONResponse({"models": models, "current": agent.current_model})


@app.post("/api/model")
async def switch_model(request: Request, body: dict[str, Any]) -> JSONResponse:
    """Switch the active model."""
    user, err = await _require_auth(request)
    if err:
        return err
    agent = await _get_user_agent(user["username"])  # type: ignore[index]
    if agent is None:
        return JSONResponse({"error": "Agent not initialized"}, status_code=503)
    model_name = body.get("model")
    if not model_name:
        return JSONResponse({"error": "No model specified"}, status_code=400)
    agent.current_model = model_name
    return JSONResponse({"success": True, "model": model_name})


@app.get("/api/memory/stats")
async def memory_stats(request: Request) -> JSONResponse:
    """Get memory statistics."""
    user, err = await _require_auth(request)
    if err:
        return err
    agent = await _get_user_agent(user["username"])  # type: ignore[index]
    if agent is None:
        return JSONResponse({"error": "Agent not initialized"}, status_code=503)
    stats = await agent.memory.get_stats()
    return JSONResponse(stats)


@app.get("/api/mcp/status")
async def mcp_status(request: Request) -> JSONResponse:
    """Get MCP server status."""
    user, err = await _require_auth(request)
    if err:
        return err
    agent = await _get_user_agent(user["username"])  # type: ignore[index]
    if agent is None:
        return JSONResponse({"error": "Agent not initialized"}, status_code=503)
    return JSONResponse(agent.mcp_manager.get_status())


@app.post("/api/mcp/reload")
async def mcp_reload(request: Request) -> JSONResponse:
    """Reload MCP configuration."""
    user, err = await _require_auth(request)
    if err:
        return err
    agent = await _get_user_agent(user["username"])  # type: ignore[index]
    if agent is None:
        return JSONResponse({"error": "Agent not initialized"}, status_code=503)
    results = await agent.mcp_manager.reload_config()
    return JSONResponse({"results": results})


@app.get("/api/database/schema")
async def database_schema(request: Request) -> JSONResponse:
    """Get the database schema."""
    user, err = await _require_auth(request)
    if err:
        return err
    agent = await _get_user_agent(user["username"])  # type: ignore[index]
    if agent is None:
        return JSONResponse({"error": "Agent not initialized"}, status_code=503)
    schema = await agent.database.get_full_schema()
    tables = await agent.database.list_tables()
    return JSONResponse({"schema_text": schema, "tables": tables})


# --- WebSocket ---

class ConnectionManager:
    """Manages WebSocket connections."""

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
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

    # Authenticate on first message
    current_user: dict[str, Any] | None = None
    user_agent = None

    try:
        while True:
            data = await websocket.receive_json()

            # Handle auth message
            if data.get("type") == "auth":
                token = data.get("token", "")
                current_user = await _get_user_from_token(token)
                if current_user:
                    user_agent = await _get_user_agent(current_user["username"])
                    await ws_manager.send_json(websocket, {
                        "type": "auth_ok",
                        "user": current_user,
                    })
                    logger.info("WebSocket authenticated: %s", current_user["username"])
                else:
                    await ws_manager.send_json(websocket, {
                        "type": "auth_error",
                        "content": "Invalid or expired token",
                    })
                continue

            # Require auth for all other messages
            if not current_user or user_agent is None:
                await ws_manager.send_json(websocket, {
                    "type": "error",
                    "content": "Not authenticated. Send auth message first.",
                })
                continue

            message = data.get("message", "")
            mode = data.get("mode", "chat")

            if not message:
                await ws_manager.send_json(websocket, {
                    "type": "error",
                    "content": "Empty message",
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
                result = await user_agent.process_message(
                    message, mode=mode, stream_callback=stream_callback
                )

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
                    "content": "Error: " + str(e),
                })

    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
        if current_user:
            logger.info("Client disconnected: %s", current_user["username"])
        else:
            logger.info("Unauthenticated client disconnected")
    except Exception as e:
        logger.error("WebSocket error: %s", e)
        ws_manager.disconnect(websocket)
