# Nexus Agent

Standalone multi-user Python AI agent that runs on your local network. Connects to your Ollama server, provides extensible MCP tool integration, persistent memory, database access, web research, USB hardware control, and a web-based chat UI. Each user gets isolated data, memory, and workspace.

## Features

- **Multi-User Support** - Login/register system with per-user isolated data, memory, and workspace
- **Ollama Integration** - Scans your server for models, automatically selects the best one for each task
- **Free AI Fallback** - When Ollama is unavailable, automatically connects to free AI (PollinationsAI, no API key needed)
- **Extensible MCP System** - Add new MCP servers by editing `mcp_config.json` (no code changes needed)
- **Persistent Memory** - SQLite-backed memory that persists across sessions (per-user)
- **Database Access** - Agent can create, modify, and query its own SQLite database (per-user)
- **Web Research** - Search the web, scrape pages, extract content
- **USB/Proxmark** - Interact with Proxmark3 and other USB serial devices (Windows COM ports + Linux /dev/tty*)
- **Chain-of-Thought Reasoning** - Transparent thinking process visible in the UI
- **Planning System** - Multi-step task planning and execution tracking
- **Web Chat UI** - Dark-themed responsive interface with Chat, Plan, and Build modes
- **Cross-Platform** - Works on Windows and Linux

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
- Git
- Node.js 18+ (optional, for MCP servers that use npx)
- Ollama running on your network (optional, free AI fallback available)

### Windows Setup

```cmd
REM Clone the repo
git clone https://github.com/puddl3jump3r/Scrollwork.git nexus-agent
cd nexus-agent

REM Run the setup script (installs deps, clones MCPs)
setup.bat

REM Activate the virtual environment
venv\Scripts\activate

REM Start the agent
python main.py
```

Open `http://localhost:8080` in your browser. Register a new account on first use.

### Linux/macOS Setup

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

Open `http://localhost:8080` in your browser. Register a new account on first use.

### Manual Setup

```bash
# Create virtual environment
python -m venv venv

# Activate (Windows)
venv\Scripts\activate
# Activate (Linux/macOS)
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Create directories
mkdir data workspace mcps

# Start the agent
python main.py
```

## Multi-User System

Each family member creates their own account via the login screen. User data is fully isolated:

```
data/
├── users.db              # Shared user accounts database
└── users/
    ├── alice/
    │   ├── memory.db     # Alice's memory
    │   └── agent.db      # Alice's database
    └── bob/
        ├── memory.db     # Bob's memory
        └── agent.db      # Bob's database

workspace/
├── alice/                # Alice's file workspace
└── bob/                  # Bob's file workspace
```

- **Registration**: Create an account with username (3+ chars) and password (4+ chars)
- **Login**: Authenticate with username/password, receives a 30-day session token
- **Isolation**: Each user has separate memory, database, workspace files, and agent instance
- **Sessions**: Token stored in browser localStorage, auto-reconnects on page reload

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
├── main.py                 # Entry point + multi-user agent manager
├── mcp_config.json         # MCP configuration (edit to add MCPs)
├── requirements.txt        # Python dependencies
├── setup.sh                # Linux/macOS setup script
├── setup.bat               # Windows setup script
├── core/
│   ├── agent.py            # Main orchestrator
│   ├── user_manager.py     # Multi-user auth & session management
│   ├── ollama_client.py    # Async Ollama API client
│   ├── free_ai_provider.py # Free AI fallback (no API key needed)
│   ├── model_selector.py   # Intelligent model selection
│   ├── memory.py           # Persistent memory system (per-user)
│   ├── database.py         # Agent-controlled database (per-user)
│   ├── mcp_manager.py      # Extensible MCP manager
│   ├── web_research.py     # Web search & scraping
│   ├── hardware.py         # USB/Proxmark interface (Windows + Linux)
│   ├── reasoning.py        # Chain-of-thought engine
│   └── planner.py          # Task planning system
├── ui/
│   ├── server.py           # FastAPI + WebSocket server with auth
│   └── static/             # Frontend (HTML/CSS/JS)
├── mcps/                   # Downloaded MCP server repos
├── data/                   # User databases (per-user subdirectories)
└── workspace/              # Agent's file workspace (per-user subdirectories)
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
