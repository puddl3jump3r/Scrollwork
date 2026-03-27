@echo off
REM Nexus Agent - Windows Setup Script
REM Requires: Python 3.12+, Git, Node.js (optional, for some MCPs)

echo.
echo  ======================================
echo   NEXUS AGENT - Windows Setup
echo  ======================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.12+ from https://python.org
    echo Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

echo [1/5] Creating Python virtual environment...
if not exist "venv" (
    python -m venv venv
)
call venv\Scripts\activate.bat

echo [2/5] Upgrading pip and installing dependencies...
python -m pip install --upgrade pip
pip install -r requirements.txt

echo [3/5] Creating data directories...
if not exist "data" mkdir data
if not exist "workspace" mkdir workspace
if not exist "mcps" mkdir mcps

echo [4/5] Setting up environment file...
if not exist ".env" (
    copy .env.example .env
    echo Created .env from .env.example
    echo Edit .env to set your Ollama host and API keys.
) else (
    echo .env already exists, skipping.
)

echo [5/5] Cloning MCP servers...

REM Check for Git
git --version >nul 2>&1
if errorlevel 1 (
    echo [WARNING] Git not found. Skipping MCP clone.
    echo Install Git from https://git-scm.com to enable MCP servers.
    goto :done
)

REM Clone MCPs if not already present
if not exist "mcps\github-mcp-server" (
    echo   Cloning github-mcp-server...
    git clone --depth 1 https://github.com/github/github-mcp-server.git mcps\github-mcp-server 2>nul
)
if not exist "mcps\playwright-mcp" (
    echo   Cloning playwright-mcp...
    git clone --depth 1 https://github.com/microsoft/playwright-mcp.git mcps\playwright-mcp 2>nul
)
if not exist "mcps\firecrawl-mcp-server" (
    echo   Cloning firecrawl-mcp-server...
    git clone --depth 1 https://github.com/firecrawl/firecrawl-mcp-server.git mcps\firecrawl-mcp-server 2>nul
)
if not exist "mcps\elevenlabs-mcp" (
    echo   Cloning elevenlabs-mcp...
    git clone --depth 1 https://github.com/elevenlabs/elevenlabs-mcp.git mcps\elevenlabs-mcp 2>nul
)
if not exist "mcps\mcp-server" (
    echo   Cloning e2b mcp-server...
    git clone --depth 1 https://github.com/e2b-dev/mcp-server.git mcps\mcp-server 2>nul
)
if not exist "mcps\ghidramcp" (
    echo   Cloning ghidramcp...
    git clone --depth 1 https://github.com/lauriewired/ghidramcp.git mcps\ghidramcp 2>nul
)
if not exist "mcps\blender-mcp" (
    echo   Cloning blender-mcp...
    git clone --depth 1 https://github.com/ahujasid/blender-mcp.git mcps\blender-mcp 2>nul
)

:done
echo.
echo  ======================================
echo   Setup Complete!
echo  ======================================
echo.
echo To start Nexus Agent:
echo   1. Activate the virtual environment:  venv\Scripts\activate
echo   2. Run the agent:                     python main.py
echo   3. Open browser to:                   http://localhost:8080
echo.
echo First time? Register a new account in the web UI.
echo Each user gets their own isolated workspace and data.
echo.
pause
