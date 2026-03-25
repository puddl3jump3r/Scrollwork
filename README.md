# Nexus Agent

Standalone Python AI agent that runs on your local network. Connects to your Ollama server, provides extensible MCP tool integration, persistent memory, database access, web research, USB hardware control, and a web-based chat UI.

## Features

- **Ollama Integration** - Scans your server for models, automatically selects the best one for each task
- **Extensible MCP System** - Add new MCP servers by editing `mcp_config.json` (no code changes needed)
- **Persistent Memory** - SQLite-backed memory that persists across sessions
- **Database Access** - Agent can create, modify, and query its own SQLite database
- **Web Research** - Search the web, scrape pages, extract content
- **USB/Proxmark** - Interact with Proxmark3 and other USB serial devices
- **Chain-of-Thought Reasoning** - Transparent thinking process visible in the UI
- **Planning System** - Multi-step task planning and execution tracking
- **Web Chat UI** - Dark-themed responsive interface with Chat, Plan, and Build modes

## Pre-configured MCP Servers

| MCP | Description | Status |
|-----|-------------|--------|
| GitHub | Repos, issues, PRs, code search | Enabled (needs token) |
| Playwright | Browser automation | Enabled |
| Firecrawl | Web scraping & crawling | Enabled (needs API key) |
| ElevenLabs | Text-to-speech | Enabled (needs API key) |
| E2B | Sandboxed code execution | Enabled (needs API key) |
| Ghidra | Binary reverse engineering | Disabled (needs Ghidra) |
| Blender | 3D modeling | Disabled (needs Blender) |

## Quick Start

### Prerequisites

- Python 3.12+
- Node.js 18+ (for MCP servers that use npx)
- Ollama running on your network

### Setup

```bash
# Clone the repo
git clone https://github.com/puddl3jump3r/Scrollwork.git nexus-agent
cd nexus-agent

# Run the setup script (installs deps, clones MCPs)
chmod +x setup.sh
./setup.sh

# Configure your environment
cp .env.example .env
# Edit .env to set your Ollama host and API keys

# Start the agent
source venv/bin/activate
python main.py
```

Open `http://localhost:8080` in your browser.

### Manual Setup

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Create directories
mkdir -p data workspace mcps

# Start the agent
python main.py
```

## Configuration

### Environment Variables (`.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server URL |
| `HOST` | `0.0.0.0` | Bind address (0.0.0.0 for LAN access) |
| `PORT` | `8080` | Web UI port |
| `WORKSPACE_DIR` | `./workspace` | Agent's file workspace |
| `DATA_DIR` | `./data` | Database storage |
| `MCP_CONFIG` | `./mcp_config.json` | MCP configuration file |

### Adding New MCPs

Edit `mcp_config.json` and add an entry:

```json
{
    "mcps": {
        "my-new-mcp": {
            "enabled": true,
            "command": "npx",
            "args": ["-y", "@some/mcp-server"],
            "env": {
                "API_KEY": "your-key-here"
            },
            "transport": "stdio",
            "description": "What this MCP does"
        }
    }
}
```

Then click the reload button in the UI sidebar, or restart the agent.

## Modes

- **Chat** - Free-form conversation with access to all tools (web search, file I/O, database, MCP tools, shell commands)
- **Plan** - Create structured multi-step plans for complex tasks
- **Build** - Create a build plan and execute it step by step

## Architecture

```
nexus-agent/
├── main.py                 # Entry point
├── mcp_config.json         # MCP configuration (edit to add MCPs)
├── requirements.txt        # Python dependencies
├── setup.sh                # One-click setup script
├── core/
│   ├── agent.py            # Main orchestrator
│   ├── ollama_client.py    # Async Ollama API client
│   ├── model_selector.py   # Intelligent model selection
│   ├── memory.py           # Persistent memory system
│   ├── database.py         # Agent-controlled database
│   ├── mcp_manager.py      # Extensible MCP manager
│   ├── web_research.py     # Web search & scraping
│   ├── hardware.py         # USB/Proxmark interface
│   ├── reasoning.py        # Chain-of-thought engine
│   └── planner.py          # Task planning system
├── ui/
│   ├── server.py           # FastAPI + WebSocket server
│   └── static/             # Frontend (HTML/CSS/JS)
├── mcps/                   # Downloaded MCP server repos
├── data/                   # SQLite databases
└── workspace/              # Agent's file workspace
```

## Built-in Agent Tools

The agent has access to these tools during conversations:

- `read_file` / `write_file` / `list_files` - Workspace file management
- `search_web` / `fetch_webpage` - Web research
- `query_database` / `modify_database` / `get_database_schema` - SQL database
- `save_memory` / `recall_memory` - Persistent memory
- `run_command` - Shell command execution
- `proxmark_command` / `list_usb_devices` - Hardware interaction
- `list_models` / `switch_model` - Ollama model management
- `create_plan` - Task planning
- All tools from connected MCP servers

## License

MIT
