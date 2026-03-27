"""Main Nexus Agent orchestrator."""

import json
import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Coroutine

from .database import DatabaseManager
from .hardware import HardwareManager
from .mcp_manager import MCPManager
from .memory import MemoryManager
from .model_selector import ModelSelector
from .free_ai_provider import FreeAIProvider
from .ollama_client import OllamaClient
from .planner import Plan, Planner, StepStatus
from .reasoning import ReasoningChain, ReasoningEngine, ThoughtType
from .web_research import WebResearcher

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are Nexus, an advanced AI agent running on the user's local network.

You have access to the following capabilities:
- File system: Read/write files in the workspace directory
- Database: Create/modify SQLite tables and run queries
- Memory: Store and recall information persistently
- Web: Search the internet, fetch and parse web pages
- Hardware: Interact with USB devices (Proxmark3, etc.)
- MCP Tools: Various specialized tools from connected MCP servers
- System: Execute shell commands on the host machine

IMPORTANT GUIDELINES:
1. Think step by step before acting
2. Use tools when you need information or need to take action
3. Store important findings in memory for future reference
4. When using the database, always check the schema first
5. Be safe with system commands - never run destructive operations
6. For complex tasks, create a plan first
7. Reflect on results and adjust your approach as needed

IMPORTANT: You MUST actually call tools to perform actions. Do NOT just describe what
you would do or output JSON examples. When you want to use a tool, you must use a
proper function/tool call. If your model supports tool calling, use the tool_calls
format. Otherwise, output EXACTLY one JSON block per tool call in this format:

```tool_call
{"name": "tool_name", "arguments": {"arg1": "value1"}}
```

After calling a tool, wait for the result before continuing.
Always explain what you're doing and why.
"""


def _build_builtin_tools() -> list[dict[str, Any]]:
    """Define built-in tools available to the agent."""
    return [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file from the workspace directory",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path relative to workspace"},
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": "Write content to a file in the workspace directory",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path relative to workspace"},
                        "content": {"type": "string", "description": "Content to write"},
                    },
                    "required": ["path", "content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "make_directory",
                "description": "Create a directory in the workspace",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Directory path relative to workspace"},
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_files",
                "description": "List files in a workspace directory",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Directory path relative to workspace (default: root)"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_web",
                "description": "Search the internet for information",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "max_results": {"type": "integer", "description": "Maximum number of results (default: 5)"},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "fetch_webpage",
                "description": "Fetch and parse a web page, extracting text content",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL to fetch"},
                    },
                    "required": ["url"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "query_database",
                "description": "Execute a SQL query on the agent's database. Use for SELECT queries.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sql": {"type": "string", "description": "SQL query to execute"},
                    },
                    "required": ["sql"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "modify_database",
                "description": "Execute a write SQL query (INSERT, UPDATE, DELETE, CREATE TABLE, etc.)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sql": {"type": "string", "description": "SQL write query to execute"},
                    },
                    "required": ["sql"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_database_schema",
                "description": "Get the full database schema showing all tables and columns",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "save_memory",
                "description": "Save important information to persistent memory",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "Information to remember"},
                        "category": {"type": "string", "description": "Category (e.g., 'fact', 'procedure', 'preference', 'project')"},
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Tags for retrieval",
                        },
                        "importance": {"type": "number", "description": "Importance 0.0-1.0 (default: 0.5)"},
                    },
                    "required": ["content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "recall_memory",
                "description": "Search and recall information from persistent memory",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query for memories"},
                        "category": {"type": "string", "description": "Filter by category"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "run_command",
                "description": "Execute a shell command on the host system",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "Shell command to execute"},
                    },
                    "required": ["command"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "proxmark_command",
                "description": "Send a command to a connected Proxmark3 device",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "Proxmark3 command to execute"},
                    },
                    "required": ["command"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_usb_devices",
                "description": "List connected USB serial devices",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_models",
                "description": "List all available Ollama models on the server",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "switch_model",
                "description": "Switch to a different Ollama model",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "model": {"type": "string", "description": "Model name to switch to"},
                    },
                    "required": ["model"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "create_plan",
                "description": "Create a structured plan for a complex task",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "goal": {"type": "string", "description": "The goal to plan for"},
                        "mode": {"type": "string", "description": "Plan mode: 'plan' or 'build'"},
                    },
                    "required": ["goal"],
                },
            },
        },
    ]


# Type alias for the streaming callback
StreamCallback = Callable[[str, str, Any], Coroutine[Any, Any, None]]


class NexusAgent:
    """Main agent that orchestrates all components."""

    def __init__(
        self,
        ollama_host: str = "http://localhost:11434",
        workspace_dir: str = "workspace",
        data_dir: str = "data",
        mcp_config: str = "mcp_config.json",
    ):
        self.ollama = OllamaClient(ollama_host)
        self.free_ai = FreeAIProvider()
        self.model_selector = ModelSelector()
        self.memory = MemoryManager(os.path.join(data_dir, "memory.db"))
        self.database = DatabaseManager(os.path.join(data_dir, "agent.db"))
        self.mcp_manager = MCPManager(mcp_config)
        self.web = WebResearcher()
        self.hardware = HardwareManager()
        self.reasoning = ReasoningEngine()
        self.planner = Planner()

        self.workspace_dir = os.path.abspath(workspace_dir)
        self.data_dir = os.path.abspath(data_dir)
        self.current_model: str | None = None
        self.session_id = str(uuid.uuid4())[:8]
        self._initialized = False
        self._using_free_ai = False

        # Ensure directories exist
        os.makedirs(self.workspace_dir, exist_ok=True)
        os.makedirs(self.data_dir, exist_ok=True)

    async def initialize(self) -> dict[str, Any]:
        """Initialize all agent subsystems."""
        status: dict[str, Any] = {}

        # Initialize memory and database
        await self.memory.initialize()
        await self.database.initialize()
        status["memory"] = True
        status["database"] = True

        # Check Ollama connection and scan models
        ollama_ok = await self.ollama.is_available()
        status["ollama"] = ollama_ok
        if ollama_ok:
            models = await self.ollama.list_models()
            self.model_selector.update_models(models)
            status["models_available"] = len(models)
            # Select a default model
            self.current_model = self.model_selector.select_model("general")
            status["selected_model"] = self.current_model
        else:
            logger.warning("Ollama server not available - trying free AI fallback")
            free_ok = await self.free_ai.initialize()
            if free_ok:
                self._using_free_ai = True
                free_models = self.free_ai.list_models()
                self.model_selector.update_models(free_models)
                status["models_available"] = len(free_models)
                self.current_model = free_models[0]["name"] if free_models else "openai-fast"
                status["selected_model"] = self.current_model
                status["ollama"] = True  # Show as connected (via free provider)
                status["provider"] = "free_ai (PollinationsAI)"
                logger.info("Free AI fallback active with %d models", len(free_models))
            else:
                status["models_available"] = 0
                status["selected_model"] = None
                logger.warning("No AI providers available")

        # Start MCP servers
        mcp_results = await self.mcp_manager.start_all()
        status["mcp"] = mcp_results

        self._initialized = True
        logger.info("Nexus Agent initialized: %s", status)
        return status

    async def shutdown(self) -> None:
        """Gracefully shut down all subsystems."""
        await self.mcp_manager.stop_all()
        await self.memory.close()
        await self.database.close()
        await self.ollama.close()
        await self.free_ai.close()
        await self.web.close()
        await self.hardware.disconnect()
        logger.info("Nexus Agent shut down")

    async def process_message(
        self,
        user_message: str,
        mode: str = "chat",
        stream_callback: StreamCallback | None = None,
    ) -> dict[str, Any]:
        """Process a user message and generate a response.

        Args:
            user_message: The user's input
            mode: Operating mode - 'chat', 'plan', or 'build'
            stream_callback: Async callback for streaming updates
                             callback(event_type, content, metadata)
        """
        if not self._initialized:
            await self.initialize()

        # Store conversation
        await self.memory.store_conversation(self.session_id, "user", user_message)

        # Start reasoning chain
        chain = self.reasoning.start_chain()
        self.reasoning.add_thought(
            ThoughtType.OBSERVATION, f"User message in {mode} mode: {user_message}"
        )

        if stream_callback:
            await stream_callback("thinking", f"Analyzing request in {mode} mode...", {})

        # Detect task type and select model
        task_type = self.model_selector.detect_task_type(user_message)
        if self.current_model is None:
            self.current_model = self.model_selector.select_model(task_type)

        if self.current_model is None:
            return {
                "response": "No AI models available. Please ensure Ollama is running with at least one model installed, or install g4f (pip install g4f) for free online AI fallback.",
                "reasoning": chain.to_dict(),
            }

        self.reasoning.add_thought(
            ThoughtType.ANALYSIS,
            f"Task type: {task_type}, Using model: {self.current_model}",
        )

        if stream_callback:
            await stream_callback(
                "thinking",
                f"Task type: {task_type} | Model: {self.current_model}",
                {},
            )

        # Handle different modes
        if mode == "plan":
            return await self._handle_plan_mode(user_message, chain, stream_callback)
        elif mode == "build":
            return await self._handle_build_mode(user_message, chain, stream_callback)
        else:
            return await self._handle_chat_mode(user_message, chain, stream_callback)

    async def _handle_chat_mode(
        self,
        message: str,
        chain: ReasoningChain,
        callback: StreamCallback | None,
    ) -> dict[str, Any]:
        """Handle a message in chat mode with tool use."""
        # Build context from memory
        recent_memories = await self.memory.recall(message, limit=5)
        memory_context = ""
        if recent_memories:
            memory_context = "\n\nRelevant memories:\n" + "\n".join(
                f"- {m['content']}" for m in recent_memories
            )

        # Build conversation history
        conv_history = await self.memory.get_conversation(self.session_id, limit=20)
        messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT + memory_context}]

        # Add conversation history (last N messages)
        for entry in conv_history[-20:]:
            messages.append({"role": entry["role"], "content": entry["content"]})

        # Add current message if not already in history
        if not conv_history or conv_history[-1]["content"] != message:
            messages.append({"role": "user", "content": message})

        # Get available tools
        tools = _build_builtin_tools()
        mcp_tools = self.mcp_manager.get_all_tools()
        tools.extend(mcp_tools)

        # Add database schema context
        schema = await self.database.get_full_schema()
        if schema and "empty" not in schema.lower():
            messages[0]["content"] += f"\n\nCurrent database schema:\n{schema}"

        # Agent loop - iterate until we get a final response
        max_iterations = 10
        for iteration in range(max_iterations):
            if callback:
                await callback("thinking", f"Thinking... (step {iteration + 1})", {})

            response = await self._chat_completion(
                model=self.current_model,  # type: ignore
                messages=messages,
                tools=tools,
            )

            msg = response.get("message", {})
            content = msg.get("content", "")
            tool_calls = msg.get("tool_calls", [])

            # If no native tool_calls, try parsing from text content
            if not tool_calls and content:
                parsed = self._parse_tool_calls_from_text(content)
                if parsed:
                    tool_calls = parsed
                    # Strip tool call blocks from content so we keep
                    # only the explanatory text for display
                    display_content = self._strip_tool_blocks(content)
                    if display_content.strip():
                        msg["content"] = display_content
                    # Set tool_calls on msg so it gets appended correctly
                    msg["tool_calls"] = tool_calls

            if not tool_calls:
                # No tool calls - this is the final response
                self.reasoning.add_thought(ThoughtType.CONCLUSION, content[:200])
                self.reasoning.complete_chain()

                # Store response
                await self.memory.store_conversation(
                    self.session_id, "assistant", content
                )

                if callback:
                    await callback("response", content, {})

                return {
                    "response": content,
                    "model": self.current_model,
                    "reasoning": chain.to_dict(),
                }

            # Process tool calls
            messages.append(msg)

            for tc in tool_calls:
                func = tc.get("function", {})
                tool_name = func.get("name", "")
                tool_args = func.get("arguments", {})

                self.reasoning.add_thought(
                    ThoughtType.ACTION,
                    f"Calling tool: {tool_name}({json.dumps(tool_args)[:200]})",
                )

                if callback:
                    await callback("tool_call", tool_name, tool_args)

                # Execute the tool
                result = await self._execute_tool(tool_name, tool_args)
                result_str = json.dumps(result) if isinstance(result, (dict, list)) else str(result)

                self.reasoning.add_thought(
                    ThoughtType.RESULT, f"Tool result: {result_str[:300]}"
                )

                if callback:
                    await callback("tool_result", result_str[:500], {"tool": tool_name})

                messages.append({
                    "role": "tool",
                    "content": result_str,
                })

        # Max iterations reached
        self.reasoning.add_thought(ThoughtType.ERROR, "Max iterations reached")
        self.reasoning.complete_chain()
        return {
            "response": "I've reached the maximum number of reasoning steps. Here's what I've gathered so far. Could you try rephrasing or breaking your request into smaller parts?",
            "reasoning": chain.to_dict(),
        }

    async def _handle_plan_mode(
        self,
        message: str,
        chain: ReasoningChain,
        callback: StreamCallback | None,
    ) -> dict[str, Any]:
        """Handle a message in plan mode - create structured plans."""
        self.reasoning.add_thought(ThoughtType.PLAN, "Creating a structured plan...")

        if callback:
            await callback("thinking", "Creating plan...", {})

        prompt = self.planner.get_planning_prompt("plan")
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"Create a plan for: {message}"},
        ]

        response = await self._chat_completion(
            model=self.current_model,  # type: ignore
            messages=messages,
        )

        content = response.get("message", {}).get("content", "")

        # Try to parse steps from the response
        steps = self._parse_plan_steps(content)
        if steps:
            plan = self.planner.create_plan(message, steps, mode="plan")
            self.reasoning.add_thought(
                ThoughtType.CONCLUSION, f"Created plan with {len(steps)} steps"
            )

            if callback:
                await callback("plan", plan.format_status(), plan.to_dict())

            result_text = f"Here's the plan:\n\n{plan.format_status()}"
        else:
            result_text = content

        self.reasoning.complete_chain()
        await self.memory.store_conversation(self.session_id, "assistant", result_text)

        return {
            "response": result_text,
            "plan": self.planner.current_plan.to_dict() if self.planner.current_plan else None,
            "reasoning": chain.to_dict(),
        }

    async def _handle_build_mode(
        self,
        message: str,
        chain: ReasoningChain,
        callback: StreamCallback | None,
    ) -> dict[str, Any]:
        """Handle a message in build mode - plan and execute."""
        self.reasoning.add_thought(ThoughtType.PLAN, "Creating build plan...")

        if callback:
            await callback("thinking", "Creating build plan...", {})

        # First create the plan
        prompt = self.planner.get_planning_prompt("build")
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"Create a build plan for: {message}"},
        ]

        response = await self._chat_completion(
            model=self.current_model,  # type: ignore
            messages=messages,
        )

        content = response.get("message", {}).get("content", "")
        steps = self._parse_plan_steps(content)

        if not steps:
            self.reasoning.complete_chain()
            return {
                "response": content,
                "reasoning": chain.to_dict(),
            }

        plan = self.planner.create_plan(message, steps, mode="build")

        if callback:
            await callback("plan", plan.format_status(), plan.to_dict())

        # Execute each step
        results: list[str] = []
        for i, step in enumerate(plan.steps):
            step.start()

            if callback:
                await callback(
                    "step_start",
                    f"Executing step {i + 1}: {step.description}",
                    {"step": i},
                )

            self.reasoning.add_thought(
                ThoughtType.ACTION, f"Executing step {i + 1}: {step.description}"
            )

            # Use chat mode to execute each step
            step_result = await self._handle_chat_mode(
                f"Execute this build step: {step.description}\n\nContext - we are building: {message}",
                chain,
                callback,
            )

            step_response = step_result.get("response", "")
            step.complete(step_response[:200])
            results.append(f"Step {i + 1}: {step_response}")

            if callback:
                await callback(
                    "step_complete",
                    f"Step {i + 1} complete",
                    {"step": i, "result": step_response[:200]},
                )

        self.reasoning.complete_chain()

        summary = f"Build plan completed!\n\n{plan.format_status()}\n\nResults:\n" + "\n\n".join(results)
        await self.memory.store_conversation(self.session_id, "assistant", summary[:2000])

        return {
            "response": summary,
            "plan": plan.to_dict(),
            "reasoning": chain.to_dict(),
        }

    def _parse_plan_steps(self, content: str) -> list[dict[str, Any]]:
        """Try to parse plan steps from LLM output."""
        # Try JSON parsing first
        try:
            # Find JSON array in the content
            start = content.find("[")
            end = content.rfind("]") + 1
            if start >= 0 and end > start:
                steps = json.loads(content[start:end])
                if isinstance(steps, list):
                    return steps
        except json.JSONDecodeError:
            pass

        # Fall back to line parsing
        steps: list[dict[str, Any]] = []
        for line in content.split("\n"):
            line = line.strip()
            # Match numbered steps or bullet points
            if line and (
                line[0].isdigit()
                or line.startswith("-")
                or line.startswith("*")
                or line.startswith("Step")
            ):
                # Clean up the line
                desc = line.lstrip("0123456789.-*) ").strip()
                if desc and len(desc) > 5:
                    steps.append({"description": desc, "tools_needed": []})

        return steps

    def _parse_tool_calls_from_text(self, content: str) -> list[dict[str, Any]]:
        """Parse tool calls embedded in text content from models that don't
        support native tool calling (e.g. mistral:7b, older llama models).

        Supports multiple formats that LLMs commonly output:
        1. ```tool_call\n{"name": "...", "arguments": {...}}\n```
        2. ```json\n{"name": "...", "arguments": {...}}\n```
        3. Bare JSON objects with "name" and "arguments" keys
        4. {"name": "tool_name", "arguments": {...}} inline in text
        """
        tool_calls: list[dict[str, Any]] = []
        known_tools = {t["function"]["name"] for t in _build_builtin_tools()}

        # Pattern 1: fenced code blocks (```tool_call, ```json, or bare ```)
        fenced_pattern = re.compile(
            r"```(?:tool_call|json)?\s*\n?\s*(\{.*?\})\s*\n?\s*```",
            re.DOTALL,
        )
        for match in fenced_pattern.finditer(content):
            parsed = self._try_parse_tool_json(match.group(1), known_tools)
            if parsed:
                tool_calls.append(parsed)

        if tool_calls:
            return tool_calls

        # Pattern 2: bare JSON objects with "name" key on their own line(s)
        # Match JSON objects that contain "name" - greedy but bounded
        bare_pattern = re.compile(
            r'\{\s*"name"\s*:\s*"(\w+)"\s*,\s*"arguments"\s*:\s*(\{.*?\})\s*\}',
            re.DOTALL,
        )
        for match in bare_pattern.finditer(content):
            name = match.group(1)
            if name in known_tools:
                try:
                    args = json.loads(match.group(2))
                    tool_calls.append({
                        "function": {"name": name, "arguments": args},
                    })
                except json.JSONDecodeError:
                    continue

        return tool_calls

    def _try_parse_tool_json(
        self, text: str, known_tools: set[str]
    ) -> dict[str, Any] | None:
        """Try to parse a JSON string as a tool call."""
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None

        if not isinstance(data, dict):
            return None

        name = data.get("name", "")
        args = data.get("arguments", {})

        if name and name in known_tools and isinstance(args, dict):
            return {"function": {"name": name, "arguments": args}}
        return None

    def _strip_tool_blocks(self, content: str) -> str:
        """Remove tool call JSON blocks from content, keeping explanation text."""
        # Remove fenced tool call blocks
        content = re.sub(
            r"```(?:tool_call|json)?\s*\n?\s*\{.*?\}\s*\n?\s*```",
            "",
            content,
            flags=re.DOTALL,
        )
        # Remove bare JSON tool call objects (possibly spanning multiple lines)
        # Match opening { with "name" key through the closing }
        content = re.sub(
            r'\{\s*\n?\s*"name"\s*:\s*"[^"]+"\s*,\s*\n?\s*"arguments"\s*:\s*\{[^{}]*\}\s*\n?\s*\}',
            "",
            content,
            flags=re.DOTALL,
        )
        # Clean up extra blank lines
        content = re.sub(r"\n{3,}", "\n\n", content)
        return content.strip()

    async def _execute_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> Any:
        """Execute a tool call and return the result."""
        try:
            # MCP tools
            if tool_name.startswith("mcp__"):
                return await self.mcp_manager.call_tool(tool_name, arguments)

            # Built-in tools
            match tool_name:
                case "read_file":
                    path = os.path.join(self.workspace_dir, arguments["path"])
                    if not os.path.abspath(path).startswith(self.workspace_dir):
                        return {"error": "Access denied: path outside workspace"}
                    if not os.path.exists(path):
                        return {"error": f"File not found: {arguments['path']}"}
                    with open(path) as f:
                        return {"content": f.read(), "path": arguments["path"]}

                case "write_file":
                    path = os.path.join(self.workspace_dir, arguments["path"])
                    if not os.path.abspath(path).startswith(self.workspace_dir):
                        return {"error": "Access denied: path outside workspace"}
                    parent = os.path.dirname(path)
                    if parent:
                        os.makedirs(parent, exist_ok=True)
                    with open(path, "w") as f:
                        f.write(arguments["content"])
                    return {"success": True, "path": arguments["path"]}

                case "make_directory":
                    path = os.path.join(self.workspace_dir, arguments["path"])
                    if not os.path.abspath(path).startswith(self.workspace_dir):
                        return {"error": "Access denied: path outside workspace"}
                    os.makedirs(path, exist_ok=True)
                    return {"success": True, "path": arguments["path"]}

                case "list_files":
                    rel_path = arguments.get("path", "")
                    path = os.path.join(self.workspace_dir, rel_path)
                    if not os.path.abspath(path).startswith(self.workspace_dir):
                        return {"error": "Access denied: path outside workspace"}
                    if not os.path.exists(path):
                        return {"error": f"Directory not found: {rel_path}"}
                    entries = []
                    for entry in os.listdir(path):
                        full = os.path.join(path, entry)
                        entries.append({
                            "name": entry,
                            "type": "directory" if os.path.isdir(full) else "file",
                            "size": os.path.getsize(full) if os.path.isfile(full) else 0,
                        })
                    return {"files": entries, "path": rel_path or "/"}

                case "search_web":
                    return await self.web.search(
                        arguments["query"],
                        arguments.get("max_results", 5),
                    )

                case "fetch_webpage":
                    return await self.web.fetch_page(arguments["url"])

                case "query_database":
                    return await self.database.execute(arguments["sql"])

                case "modify_database":
                    rows = await self.database.execute_write(arguments["sql"])
                    return {"affected_rows": rows, "success": True}

                case "get_database_schema":
                    return {"schema": await self.database.get_full_schema()}

                case "save_memory":
                    mid = await self.memory.store(
                        arguments["content"],
                        arguments.get("category", "general"),
                        arguments.get("tags"),
                        arguments.get("importance", 0.5),
                    )
                    return {"memory_id": mid, "success": True}

                case "recall_memory":
                    return await self.memory.recall(
                        arguments.get("query"),
                        arguments.get("category"),
                        limit=10,
                    )

                case "run_command":
                    return await self.hardware.execute_system_command(
                        arguments["command"]
                    )

                case "proxmark_command":
                    return await self.hardware.proxmark_command(arguments["command"])

                case "list_usb_devices":
                    return await self.hardware.list_usb_devices()

                case "list_models":
                    models = await self.ollama.list_models()
                    return [
                        {
                            "name": m.get("name"),
                            "size": m.get("size"),
                            "modified": m.get("modified_at"),
                        }
                        for m in models
                    ]

                case "switch_model":
                    model_name = arguments["model"]
                    models = await self.ollama.list_models()
                    available = [m["name"] for m in models]
                    if model_name not in available:
                        return {"error": f"Model '{model_name}' not found. Available: {available}"}
                    self.current_model = model_name
                    return {"success": True, "model": model_name}

                case "create_plan":
                    # This triggers plan mode for the next iteration
                    return {"info": "Plan creation will be handled in the planning system"}

                case _:
                    return {"error": f"Unknown tool: {tool_name}"}

        except Exception as e:
            logger.error("Tool execution error (%s): %s", tool_name, e)
            return {"error": str(e)}

    async def _chat_completion(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
    ) -> dict[str, Any]:
        """Route chat completion to either Ollama or free AI provider."""
        if self._using_free_ai:
            return await self.free_ai.chat(
                model=model,
                messages=messages,
                tools=tools,
                temperature=temperature,
            )
        return await self.ollama.chat(
            model=model,
            messages=messages,
            tools=tools,
            temperature=temperature,
        )

    def get_status(self) -> dict[str, Any]:
        """Get the current agent status."""
        has_models = len(self.model_selector.available_models) > 0
        status = {
            "initialized": self._initialized,
            "session_id": self.session_id,
            "current_model": self.current_model,
            "models_available": len(self.model_selector.available_models),
            "ollama": has_models,
            "memory": True,
            "database": True,
            "mcp_status": self.mcp_manager.get_status(),
            "workspace": self.workspace_dir,
            "active_plan": self.planner.current_plan.to_dict() if self.planner.current_plan else None,
        }
        if self._using_free_ai:
            status["provider"] = "free_ai (PollinationsAI)"
        else:
            status["provider"] = "ollama"
        return status
