#!/usr/bin/env bash
# Nexus Agent - Setup Script
# Installs all dependencies and downloads MCP servers

set -e

echo "╔══════════════════════════════════════════╗"
echo "║         NEXUS AGENT SETUP v1.0           ║"
echo "╚══════════════════════════════════════════╝"
echo ""

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

# --- Check Prerequisites ---
echo "[1/6] Checking prerequisites..."

# Python
if ! command -v python3 &>/dev/null; then
    echo "ERROR: Python 3 is required. Install Python 3.12+"
    exit 1
fi
PYTHON_VER=$(python3 --version 2>&1)
echo "  Python: $PYTHON_VER"

# Node.js (needed for most MCPs)
if ! command -v node &>/dev/null; then
    echo "  WARNING: Node.js not found. Installing via nvm..."
    curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
    export NVM_DIR="$HOME/.nvm"
    [ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
    nvm install --lts
    echo "  Node.js installed: $(node --version)"
else
    echo "  Node.js: $(node --version)"
fi

# npm/npx
if ! command -v npx &>/dev/null; then
    echo "  WARNING: npx not found. Install Node.js 18+ which includes npx."
fi

# --- Create Virtual Environment ---
echo ""
echo "[2/6] Setting up Python virtual environment..."

if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "  Created virtual environment"
else
    echo "  Virtual environment already exists"
fi

source venv/bin/activate
echo "  Activated venv ($(python --version))"

# --- Install Python Dependencies ---
echo ""
echo "[3/6] Installing Python dependencies..."

pip install --upgrade pip -q
pip install -r requirements.txt -q
echo "  All Python packages installed"

# --- Create Directories ---
echo ""
echo "[4/6] Creating directories..."

mkdir -p data workspace mcps
echo "  Created data/, workspace/, mcps/"

# --- Download MCP Servers ---
echo ""
echo "[5/6] Downloading MCP servers..."

cd mcps

# GhidraMCP
if [ ! -d "ghidramcp" ]; then
    echo "  Cloning GhidraMCP..."
    git clone --depth 1 https://github.com/lauriewired/ghidramcp.git ghidramcp 2>/dev/null || echo "  WARNING: Could not clone GhidraMCP"
else
    echo "  GhidraMCP already downloaded"
fi

# Blender MCP
if [ ! -d "blender-mcp" ]; then
    echo "  Cloning Blender MCP..."
    git clone --depth 1 https://github.com/ahujasid/blender-mcp.git blender-mcp 2>/dev/null || echo "  WARNING: Could not clone Blender MCP"
else
    echo "  Blender MCP already downloaded"
fi

# GitHub MCP Server
if [ ! -d "github-mcp-server" ]; then
    echo "  Cloning GitHub MCP Server..."
    git clone --depth 1 https://github.com/github/github-mcp-server.git github-mcp-server 2>/dev/null || echo "  WARNING: Could not clone GitHub MCP Server"
else
    echo "  GitHub MCP Server already downloaded"
fi

# ElevenLabs MCP
if [ ! -d "elevenlabs-mcp" ]; then
    echo "  Cloning ElevenLabs MCP..."
    git clone --depth 1 https://github.com/elevenlabs/elevenlabs-mcp.git elevenlabs-mcp 2>/dev/null || echo "  WARNING: Could not clone ElevenLabs MCP"
else
    echo "  ElevenLabs MCP already downloaded"
fi

# Playwright MCP
if [ ! -d "playwright-mcp" ]; then
    echo "  Cloning Playwright MCP..."
    git clone --depth 1 https://github.com/microsoft/playwright-mcp.git playwright-mcp 2>/dev/null || echo "  WARNING: Could not clone Playwright MCP"
else
    echo "  Playwright MCP already downloaded"
fi

# E2B MCP
if [ ! -d "e2b-mcp-server" ]; then
    echo "  Cloning E2B MCP Server..."
    git clone --depth 1 https://github.com/e2b-dev/mcp-server.git e2b-mcp-server 2>/dev/null || echo "  WARNING: Could not clone E2B MCP Server"
else
    echo "  E2B MCP Server already downloaded"
fi

# Firecrawl MCP
if [ ! -d "firecrawl-mcp-server" ]; then
    echo "  Cloning Firecrawl MCP Server..."
    git clone --depth 1 https://github.com/firecrawl/firecrawl-mcp-server.git firecrawl-mcp-server 2>/dev/null || echo "  WARNING: Could not clone Firecrawl MCP Server"
else
    echo "  Firecrawl MCP Server already downloaded"
fi

cd "$PROJECT_DIR"

# Pre-cache npx packages (so first run is faster)
echo ""
echo "  Pre-caching MCP npm packages..."
npx -y @modelcontextprotocol/server-github --help >/dev/null 2>&1 || true
npx -y @playwright/mcp@latest --help >/dev/null 2>&1 || true
npx -y firecrawl-mcp --help >/dev/null 2>&1 || true
npx -y @elevenlabs/mcp-server --help >/dev/null 2>&1 || true
npx -y @e2b/mcp-server --help >/dev/null 2>&1 || true
echo "  NPM packages cached"

# --- Setup .env ---
echo ""
echo "[6/6] Environment configuration..."

if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "  Created .env from template"
    echo "  IMPORTANT: Edit .env to add your API keys for MCP servers"
else
    echo "  .env already exists (not overwriting)"
fi

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║           SETUP COMPLETE!                ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "Next steps:"
echo "  1. Edit .env to configure your Ollama host and API keys"
echo "  2. Edit mcp_config.json to enable/disable MCP servers"
echo "  3. Start the agent:"
echo ""
echo "     source venv/bin/activate"
echo "     python main.py"
echo ""
echo "  4. Open http://localhost:8080 in your browser"
echo ""
echo "To add new MCPs:"
echo "  - Add an entry to mcp_config.json"
echo "  - Click 'Reload' in the UI or restart the agent"
echo "  - No code changes needed!"
echo ""
