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
from core.user_manager import UserManager
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
    ║             NEXUS AGENT v1.1             ║
    ║      Multi-User Local AI Framework       ║
    ╚══════════════════════════════════════════╝
    """
    print(banner)


class AgentManager:
    """Manages per-user NexusAgent instances and shared resources."""

    def __init__(
        self,
        ollama_host: str,
        data_dir: str,
        workspace_dir: str,
        mcp_config: str,
    ) -> None:
        self.ollama_host = ollama_host
        self.data_dir = os.path.abspath(data_dir)
        self.workspace_dir = os.path.abspath(workspace_dir)
        self.mcp_config = mcp_config
        self.user_manager = UserManager(self.data_dir)
        self._agents: dict[str, NexusAgent] = {}
        self._agent_locks: dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Initialize shared resources."""
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.workspace_dir, exist_ok=True)
        await self.user_manager.initialize()
        logger.info("Agent manager initialized")
        logger.info("  Ollama: %s", self.ollama_host)
        logger.info("  Data: %s", self.data_dir)
        logger.info("  Workspace: %s", self.workspace_dir)

    async def get_agent(self, username: str) -> NexusAgent:
        """Get or create an agent instance for a specific user.

        Uses per-user locks to prevent duplicate initialization when
        multiple requests arrive concurrently for the same user.
        """
        if username in self._agents:
            return self._agents[username]

        # Get or create a per-user lock
        async with self._global_lock:
            if username not in self._agent_locks:
                self._agent_locks[username] = asyncio.Lock()
            user_lock = self._agent_locks[username]

        async with user_lock:
            # Double-check after acquiring lock
            if username in self._agents:
                return self._agents[username]

            # Per-user directories
            user_data = self.user_manager.get_user_data_dir(username)
            user_workspace = self.user_manager.get_user_workspace_dir(username)

            agent = NexusAgent(
                ollama_host=self.ollama_host,
                workspace_dir=user_workspace,
                data_dir=user_data,
                mcp_config=self.mcp_config,
            )

            logger.info("Initializing agent for user: %s", username)
            status = await agent.initialize()

            logger.info("Agent ready for %s: ollama=%s models=%s",
                        username, status.get("ollama", False),
                        status.get("models_available", 0))

            self._agents[username] = agent
            return agent

    async def remove_agent(self, username: str) -> None:
        """Shut down and remove a user's agent instance."""
        agent = self._agents.pop(username, None)
        if agent:
            await agent.shutdown()
            logger.info("Agent shut down for user: %s", username)

    async def shutdown(self) -> None:
        """Shut down all agent instances."""
        for username, agent in self._agents.items():
            try:
                await agent.shutdown()
                logger.info("Shut down agent for: %s", username)
            except Exception as e:
                logger.error("Error shutting down agent for %s: %s", username, e)
        self._agents.clear()
        await self.user_manager.close()
        logger.info("Agent manager shut down")


def main() -> None:
    """Main entry point."""
    print_banner()

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))
    ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    data_dir = os.getenv("DATA_DIR", str(PROJECT_ROOT / "data"))
    workspace_dir = os.getenv("WORKSPACE_DIR", str(PROJECT_ROOT / "workspace"))
    mcp_config = os.getenv("MCP_CONFIG", str(PROJECT_ROOT / "mcp_config.json"))

    # Create the agent manager
    manager = AgentManager(
        ollama_host=ollama_host,
        data_dir=data_dir,
        workspace_dir=workspace_dir,
        mcp_config=mcp_config,
    )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        loop.run_until_complete(manager.initialize())
    except Exception as e:
        logger.error("Failed to initialize agent manager: %s", e)
        logger.info("Starting server anyway - will retry on first request")

    # Inject manager into the server module
    import ui.server as server_module
    server_module.agent_manager = manager

    # Handle graceful shutdown (Windows-safe: SIGTERM not available)
    def shutdown_handler(sig: int, frame: object) -> None:
        logger.info("Shutting down...")
        loop.run_until_complete(manager.shutdown())
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown_handler)
    if sys.platform != "win32":
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
        loop.run_until_complete(manager.shutdown())
        loop.close()


if __name__ == "__main__":
    main()
