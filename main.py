#!/usr/bin/env python3
"""Nexus Agent - Main entry point."""

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

# Add project root to path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.agent import NexusAgent
from ui.server import app

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("nexus")


def print_banner() -> None:
    """Print the startup banner."""
    banner = r"""
    ╔══════════════════════════════════════════╗
    ║             NEXUS AGENT v1.0             ║
    ║        Local AI Agent Framework          ║
    ╚══════════════════════════════════════════╝
    """
    print(banner)


async def initialize_agent() -> NexusAgent:
    """Initialize the Nexus Agent and all subsystems."""
    ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    workspace_dir = os.getenv("WORKSPACE_DIR", str(PROJECT_ROOT / "workspace"))
    data_dir = os.getenv("DATA_DIR", str(PROJECT_ROOT / "data"))
    mcp_config = os.getenv("MCP_CONFIG", str(PROJECT_ROOT / "mcp_config.json"))

    agent = NexusAgent(
        ollama_host=ollama_host,
        workspace_dir=workspace_dir,
        data_dir=data_dir,
        mcp_config=mcp_config,
    )

    logger.info("Initializing Nexus Agent...")
    logger.info("  Ollama: %s", ollama_host)
    logger.info("  Workspace: %s", workspace_dir)
    logger.info("  Data: %s", data_dir)
    logger.info("  MCP Config: %s", mcp_config)

    status = await agent.initialize()

    logger.info("Initialization complete:")
    logger.info("  Ollama connected: %s", status.get("ollama", False))
    logger.info("  Models available: %s", status.get("models_available", 0))
    logger.info("  Selected model: %s", status.get("selected_model", "none"))

    mcp_status = status.get("mcp", {})
    connected = sum(1 for v in mcp_status.values() if v)
    logger.info("  MCP servers: %d/%d connected", connected, len(mcp_status))

    return agent


def main() -> None:
    """Main entry point."""
    print_banner()

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))

    # Initialize agent before starting server
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        agent = loop.run_until_complete(initialize_agent())
    except Exception as e:
        logger.error("Failed to initialize agent: %s", e)
        logger.info("Starting server anyway - agent will retry on first request")
        agent = NexusAgent(
            ollama_host=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
            workspace_dir=os.getenv("WORKSPACE_DIR", str(PROJECT_ROOT / "workspace")),
            data_dir=os.getenv("DATA_DIR", str(PROJECT_ROOT / "data")),
            mcp_config=os.getenv("MCP_CONFIG", str(PROJECT_ROOT / "mcp_config.json")),
        )

    # Inject agent into the server module
    import ui.server as server_module
    server_module.agent = agent

    # Handle graceful shutdown
    def shutdown_handler(sig: int, frame: object) -> None:
        logger.info("Shutting down...")
        loop.run_until_complete(agent.shutdown())
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    logger.info("Starting Nexus Agent at http://%s:%d", host, port)
    logger.info("Open the UI in your browser to start chatting!")

    # Run the server
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
        access_log=False,
    )
    server = uvicorn.Server(config)

    try:
        loop.run_until_complete(server.serve())
    except KeyboardInterrupt:
        logger.info("Interrupted - shutting down...")
    finally:
        loop.run_until_complete(agent.shutdown())
        loop.close()


if __name__ == "__main__":
    main()
