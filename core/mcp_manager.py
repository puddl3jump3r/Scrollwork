"""Extensible MCP (Model Context Protocol) manager.

Users add new MCPs by editing mcp_config.json - no core code changes needed.
"""

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class MCPServerConnection:
    """Represents a connection to a single MCP server via stdio."""

    def __init__(self, name: str, config: dict[str, Any]):
        self.name = name
        self.config = config
        self.process: asyncio.subprocess.Process | None = None
        self.tools: list[dict[str, Any]] = []
        self.connected = False
        self._read_lock = asyncio.Lock()
        self._request_id = 0

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def start(self) -> bool:
        """Start the MCP server process and initialize connection."""
        command = self.config.get("command", "")
        args = self.config.get("args", [])
        env_vars = self.config.get("env", {})

        if not command:
            logger.error("No command specified for MCP '%s'", self.name)
            return False

        # Build environment
        env = os.environ.copy()
        for key, value in env_vars.items():
            resolved = os.path.expandvars(value)
            if resolved and resolved != value or value:
                env[key] = resolved

        try:
            full_cmd = [command] + args
            logger.info("Starting MCP '%s': %s", self.name, " ".join(full_cmd))
            self.process = await asyncio.create_subprocess_exec(
                *full_cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            # Send initialize request
            init_result = await self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "nexus-agent", "version": "1.0.0"},
            })

            if init_result is None:
                logger.error("Failed to initialize MCP '%s'", self.name)
                await self.stop()
                return False

            # Send initialized notification
            await self._send_notification("notifications/initialized", {})

            # Discover tools
            tools_result = await self._send_request("tools/list", {})
            if tools_result and "tools" in tools_result:
                self.tools = tools_result["tools"]
                logger.info(
                    "MCP '%s' connected with %d tools", self.name, len(self.tools)
                )
            else:
                self.tools = []
                logger.info("MCP '%s' connected (no tools reported)", self.name)

            self.connected = True
            return True

        except FileNotFoundError:
            logger.error(
                "Command not found for MCP '%s': %s", self.name, command
            )
            return False
        except Exception as e:
            logger.error("Error starting MCP '%s': %s", self.name, e)
            return False

    async def _send_request(
        self, method: str, params: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Send a JSON-RPC request to the MCP server."""
        if not self.process or not self.process.stdin or not self.process.stdout:
            return None

        request_id = self._next_id()
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }

        try:
            msg = json.dumps(request)
            content = f"Content-Length: {len(msg)}\r\n\r\n{msg}"
            self.process.stdin.write(content.encode())
            await self.process.stdin.drain()

            # Read response
            async with self._read_lock:
                response = await asyncio.wait_for(
                    self._read_response(), timeout=30.0
                )
            return response
        except asyncio.TimeoutError:
            logger.error("Timeout waiting for MCP '%s' response", self.name)
            return None
        except Exception as e:
            logger.error("Error communicating with MCP '%s': %s", self.name, e)
            return None

    async def _send_notification(
        self, method: str, params: dict[str, Any]
    ) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        if not self.process or not self.process.stdin:
            return

        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }

        try:
            msg = json.dumps(notification)
            content = f"Content-Length: {len(msg)}\r\n\r\n{msg}"
            self.process.stdin.write(content.encode())
            await self.process.stdin.drain()
        except Exception as e:
            logger.error("Error sending notification to MCP '%s': %s", self.name, e)

    async def _read_response(self) -> dict[str, Any] | None:
        """Read a JSON-RPC response from the MCP server."""
        if not self.process or not self.process.stdout:
            return None

        try:
            # Read headers
            content_length = 0
            while True:
                line = await asyncio.wait_for(
                    self.process.stdout.readline(), timeout=30.0
                )
                line_str = line.decode().strip()
                if not line_str:
                    break
                if line_str.lower().startswith("content-length:"):
                    content_length = int(line_str.split(":")[1].strip())

            if content_length == 0:
                return None

            # Read body
            body = await asyncio.wait_for(
                self.process.stdout.readexactly(content_length), timeout=30.0
            )
            data = json.loads(body.decode())

            if "error" in data:
                logger.error("MCP '%s' error: %s", self.name, data["error"])
                return None

            return data.get("result")
        except Exception as e:
            logger.error("Error reading MCP '%s' response: %s", self.name, e)
            return None

    async def call_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Call a tool on this MCP server."""
        result = await self._send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })

        if result is None:
            return {"error": f"Failed to call tool '{tool_name}' on MCP '{self.name}'"}

        return result

    async def stop(self) -> None:
        """Stop the MCP server process."""
        if self.process:
            try:
                self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self.process.kill()
            except Exception:
                pass
            self.process = None
        self.connected = False
        self.tools = []


class MCPManager:
    """Manages multiple MCP server connections via config file.

    To add a new MCP:
    1. Add an entry to mcp_config.json
    2. Restart the agent (or call reload_config())

    No code changes needed.
    """

    def __init__(self, config_path: str = "mcp_config.json"):
        self.config_path = config_path
        self.servers: dict[str, MCPServerConnection] = {}
        self._config: dict[str, Any] = {}

    def load_config(self) -> dict[str, Any]:
        """Load MCP configuration from file."""
        config_file = Path(self.config_path)
        if not config_file.exists():
            logger.warning("MCP config not found at %s", self.config_path)
            return {}

        try:
            with open(config_file) as f:
                self._config = json.load(f)
            return self._config
        except Exception as e:
            logger.error("Error loading MCP config: %s", e)
            return {}

    async def start_all(self) -> dict[str, bool]:
        """Start all enabled MCP servers from config."""
        config = self.load_config()
        mcps = config.get("mcps", {})
        results: dict[str, bool] = {}

        for name, mcp_config in mcps.items():
            if not mcp_config.get("enabled", True):
                logger.info("MCP '%s' is disabled, skipping", name)
                results[name] = False
                continue

            server = MCPServerConnection(name, mcp_config)
            success = await server.start()
            results[name] = success
            if success:
                self.servers[name] = server
            else:
                logger.warning("Failed to start MCP '%s'", name)

        logger.info(
            "MCP startup complete: %d/%d connected",
            sum(results.values()),
            len(results),
        )
        return results

    async def stop_all(self) -> None:
        """Stop all MCP servers."""
        for name, server in self.servers.items():
            logger.info("Stopping MCP '%s'", name)
            await server.stop()
        self.servers.clear()

    async def reload_config(self) -> dict[str, bool]:
        """Reload configuration and restart servers."""
        await self.stop_all()
        return await self.start_all()

    def get_all_tools(self) -> list[dict[str, Any]]:
        """Get all tools from all connected MCP servers.

        Returns tools in Ollama/OpenAI function calling format.
        """
        all_tools: list[dict[str, Any]] = []
        for server_name, server in self.servers.items():
            for tool in server.tools:
                # Convert MCP tool schema to OpenAI function format
                func_tool = {
                    "type": "function",
                    "function": {
                        "name": f"mcp__{server_name}__{tool['name']}",
                        "description": tool.get("description", f"MCP tool from {server_name}"),
                        "parameters": tool.get("inputSchema", {
                            "type": "object",
                            "properties": {},
                        }),
                    },
                }
                all_tools.append(func_tool)
        return all_tools

    def get_tool_descriptions(self) -> str:
        """Get a human-readable description of all available MCP tools."""
        lines: list[str] = []
        for server_name, server in self.servers.items():
            if server.tools:
                lines.append(f"\n[{server_name}] ({len(server.tools)} tools):")
                for tool in server.tools:
                    desc = tool.get("description", "No description")
                    lines.append(f"  - {tool['name']}: {desc}")
        if not lines:
            return "No MCP tools available."
        return "Available MCP Tools:" + "\n".join(lines)

    async def call_tool(
        self, full_tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Call an MCP tool by its full name (mcp__server__tool)."""
        parts = full_tool_name.split("__", 2)
        if len(parts) != 3 or parts[0] != "mcp":
            return {"error": f"Invalid MCP tool name format: {full_tool_name}"}

        server_name = parts[1]
        tool_name = parts[2]

        server = self.servers.get(server_name)
        if not server:
            return {"error": f"MCP server '{server_name}' not connected"}

        if not server.connected:
            return {"error": f"MCP server '{server_name}' is not connected"}

        return await server.call_tool(tool_name, arguments)

    def get_status(self) -> dict[str, Any]:
        """Get status of all MCP servers."""
        config = self._config.get("mcps", {})
        status: dict[str, Any] = {}
        for name in config:
            server = self.servers.get(name)
            status[name] = {
                "enabled": config[name].get("enabled", True),
                "connected": server.connected if server else False,
                "tools_count": len(server.tools) if server else 0,
                "description": config[name].get("description", ""),
            }
        return status
