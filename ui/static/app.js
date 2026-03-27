// Nexus Agent - Frontend Application

class NexusApp {
    constructor() {
        this.ws = null;
        this.currentMode = 'chat';
        this.isConnected = false;
        this.isProcessing = false;
        this.showThinking = true;
        this.autoScroll = true;
        this.messageHistory = [];
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 10;
        this.reconnectDelay = 2000;
        this.authToken = localStorage.getItem('nexus_token');
        this.currentUser = null;

        this.init();
    }

    init() {
        this.bindLoginEvents();
        if (this.authToken) {
            this.checkAuth();
        } else {
            this.showLoginScreen();
        }
    }

    initApp() {
        this.bindElements();
        this.bindEvents();
        this.connectWebSocket();
        this.loadStatus();
        this.loadModels();
        this.loadMCPStatus();
        this.updateUserProfile();
    }

    bindElements() {
        this.messagesEl = document.getElementById('messages');
        this.inputEl = document.getElementById('message-input');
        this.sendBtn = document.getElementById('send-btn');
        this.modelSelect = document.getElementById('model-select');
        this.modelInfo = document.getElementById('model-info');
        this.thinkingIndicator = document.getElementById('thinking-indicator');
        this.thinkingText = document.getElementById('thinking-text');
        this.planPanel = document.getElementById('plan-panel');
        this.planContent = document.getElementById('plan-content');
        this.planProgressBar = document.getElementById('plan-progress-bar');
        this.charCount = document.getElementById('char-count');
        this.modeLabel = document.getElementById('current-mode-label');
        this.mcpPanel = document.getElementById('mcp-panel');
    }

    // --- Auth Methods ---

    bindLoginEvents() {
        document.getElementById('login-btn').addEventListener('click', () => this.doLogin());
        document.getElementById('register-btn').addEventListener('click', () => this.doRegister());

        document.getElementById('show-register').addEventListener('click', (e) => {
            e.preventDefault();
            document.getElementById('login-form').classList.add('hidden');
            document.getElementById('register-form').classList.remove('hidden');
        });

        document.getElementById('show-login').addEventListener('click', (e) => {
            e.preventDefault();
            document.getElementById('register-form').classList.add('hidden');
            document.getElementById('login-form').classList.remove('hidden');
        });

        // Enter key on login fields
        document.getElementById('login-password').addEventListener('keydown', (e) => {
            if (e.key === 'Enter') this.doLogin();
        });
        document.getElementById('register-confirm').addEventListener('keydown', (e) => {
            if (e.key === 'Enter') this.doRegister();
        });
    }

    showLoginScreen() {
        document.getElementById('login-screen').classList.remove('hidden');
        document.getElementById('app').classList.add('hidden');
        // Reset to login form (not register) and clear inputs
        document.getElementById('login-form').classList.remove('hidden');
        document.getElementById('register-form').classList.add('hidden');
        document.getElementById('login-username').value = '';
        document.getElementById('login-password').value = '';
        document.getElementById('register-username').value = '';
        document.getElementById('register-display').value = '';
        document.getElementById('register-password').value = '';
        document.getElementById('register-confirm').value = '';
        document.getElementById('login-error').classList.add('hidden');
        document.getElementById('register-error').classList.add('hidden');
    }

    showAppScreen() {
        document.getElementById('login-screen').classList.add('hidden');
        document.getElementById('app').classList.remove('hidden');
    }

    async checkAuth() {
        try {
            const resp = await this.authFetch('/api/auth/me');
            if (resp.ok) {
                const data = await resp.json();
                if (data.authenticated) {
                    this.currentUser = data.user;
                    this.showAppScreen();
                    this.initApp();
                    return;
                }
            }
        } catch (e) {
            console.error('Auth check failed:', e);
        }
        // Token invalid or expired
        this.authToken = null;
        localStorage.removeItem('nexus_token');
        this.showLoginScreen();
    }

    async doLogin() {
        const username = document.getElementById('login-username').value.trim();
        const password = document.getElementById('login-password').value;
        const errorEl = document.getElementById('login-error');

        if (!username || !password) {
            errorEl.textContent = 'Please enter username and password';
            errorEl.classList.remove('hidden');
            return;
        }

        try {
            const resp = await fetch('/api/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password }),
            });
            const data = await resp.json();

            if (data.success) {
                this.authToken = data.token;
                this.currentUser = data.user;
                localStorage.setItem('nexus_token', data.token);
                errorEl.classList.add('hidden');
                this.showAppScreen();
                this.initApp();
            } else {
                errorEl.textContent = data.error || 'Login failed';
                errorEl.classList.remove('hidden');
            }
        } catch (e) {
            errorEl.textContent = 'Could not reach server';
            errorEl.classList.remove('hidden');
        }
    }

    async doRegister() {
        const username = document.getElementById('register-username').value.trim();
        const displayName = document.getElementById('register-display').value.trim();
        const password = document.getElementById('register-password').value;
        const confirm = document.getElementById('register-confirm').value;
        const errorEl = document.getElementById('register-error');

        if (!username || !password) {
            errorEl.textContent = 'Please fill in username and password';
            errorEl.classList.remove('hidden');
            return;
        }
        if (password !== confirm) {
            errorEl.textContent = 'Passwords do not match';
            errorEl.classList.remove('hidden');
            return;
        }

        try {
            const resp = await fetch('/api/auth/register', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password, display_name: displayName || undefined }),
            });
            const data = await resp.json();

            if (data.success) {
                this.authToken = data.token;
                this.currentUser = data.user;
                localStorage.setItem('nexus_token', data.token);
                errorEl.classList.add('hidden');
                this.showAppScreen();
                this.initApp();
            } else {
                errorEl.textContent = data.error || 'Registration failed';
                errorEl.classList.remove('hidden');
            }
        } catch (e) {
            errorEl.textContent = 'Could not reach server';
            errorEl.classList.remove('hidden');
        }
    }

    async doLogout() {
        try {
            await this.authFetch('/api/auth/logout', { method: 'POST' });
        } catch (e) {
            // ignore
        }
        this.authToken = null;
        this.currentUser = null;
        localStorage.removeItem('nexus_token');
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
        this.showLoginScreen();
    }

    authFetch(url, options = {}) {
        const headers = options.headers || {};
        if (this.authToken) {
            headers['Authorization'] = 'Bearer ' + this.authToken;
        }
        return fetch(url, { ...options, headers });
    }

    updateUserProfile() {
        if (this.currentUser) {
            const avatarEl = document.getElementById('user-avatar');
            const nameEl = document.getElementById('user-display-name');
            avatarEl.textContent = (this.currentUser.display_name || this.currentUser.username)[0].toUpperCase();
            nameEl.textContent = this.currentUser.display_name || this.currentUser.username;
        }
    }

    bindEvents() {
        // Send message
        this.sendBtn.addEventListener('click', () => this.sendMessage());
        this.inputEl.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendMessage();
            }
        });

        // Auto-resize textarea
        this.inputEl.addEventListener('input', () => {
            this.inputEl.style.height = 'auto';
            this.inputEl.style.height = Math.min(this.inputEl.scrollHeight, 200) + 'px';
            this.charCount.textContent = this.inputEl.value.length;
        });

        // Mode selector
        document.querySelectorAll('.mode-btn').forEach(btn => {
            btn.addEventListener('click', () => this.setMode(btn.dataset.mode));
        });

        // Model selector
        this.modelSelect.addEventListener('change', () => this.switchModel());

        // Settings
        document.getElementById('show-thinking').addEventListener('change', (e) => {
            this.showThinking = e.target.checked;
            document.querySelectorAll('.thinking-message, .thinking-toggle, .tool-message').forEach(el => {
                el.style.display = this.showThinking ? '' : 'none';
            });
        });

        document.getElementById('auto-scroll').addEventListener('change', (e) => {
            this.autoScroll = e.target.checked;
        });

        // Clear chat
        document.getElementById('clear-chat-btn').addEventListener('click', () => {
            this.messagesEl.innerHTML = '';
            this.addSystemMessage('Chat cleared. Ready for new conversation.');
        });

        // New session
        document.getElementById('new-session-btn').addEventListener('click', () => {
            this.messagesEl.innerHTML = '';
            this.addSystemMessage('New session started. All context reset.');
            if (this.ws) {
                this.ws.close();
                this.connectWebSocket();
            }
        });

        // MCP reload
        document.getElementById('mcp-reload-btn').addEventListener('click', () => this.reloadMCP());

        // Close plan panel
        document.getElementById('close-plan-btn').addEventListener('click', () => {
            this.planPanel.classList.add('hidden');
        });

        // Logout
        document.getElementById('logout-btn').addEventListener('click', () => this.doLogout());
    }

    // WebSocket Connection
    connectWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/chat`;

        this.ws = new WebSocket(wsUrl);

        this.ws.onopen = () => {
            this.reconnectAttempts = 0;
            console.log('WebSocket connected, sending auth...');
            // Authenticate the WebSocket connection
            if (this.authToken) {
                this.ws.send(JSON.stringify({ type: 'auth', token: this.authToken }));
            }
        };

        this.ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            this.handleServerMessage(data);
        };

        this.ws.onclose = () => {
            this.isConnected = false;
            this.updateConnectionStatus(false);
            console.log('WebSocket disconnected');
            this.attemptReconnect();
        };

        this.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
        };
    }

    attemptReconnect() {
        if (this.reconnectAttempts < this.maxReconnectAttempts) {
            this.reconnectAttempts++;
            const delay = this.reconnectDelay * this.reconnectAttempts;
            console.log(`Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})...`);
            setTimeout(() => this.connectWebSocket(), delay);
        }
    }

    updateConnectionStatus(connected) {
        const ollamaStatus = document.getElementById('ollama-status');
        if (connected) {
            ollamaStatus.className = 'status-dot online';
        } else {
            ollamaStatus.className = 'status-dot offline';
        }
    }

    // Message Handling
    handleServerMessage(data) {
        switch (data.type) {
            case 'auth_ok':
                this.isConnected = true;
                this.updateConnectionStatus(true);
                console.log('WebSocket authenticated');
                break;

            case 'auth_error':
                console.error('WebSocket auth failed:', data.content);
                this.doLogout();
                break;

            case 'ack':
                this.setProcessing(true);
                break;

            case 'thinking':
                this.updateThinking(data.content);
                if (this.showThinking) {
                    this.addThinkingMessage(data.content);
                }
                break;

            case 'tool_call':
                if (this.showThinking) {
                    this.addToolCallMessage(data.content, data.metadata);
                }
                break;

            case 'tool_result':
                if (this.showThinking) {
                    this.addToolResultMessage(data.content, data.metadata);
                }
                break;

            case 'plan':
                this.showPlan(data.content, data.metadata);
                break;

            case 'step_start':
            case 'step_complete':
                this.updatePlanStep(data);
                break;

            case 'final_response':
                this.setProcessing(false);
                this.addAssistantMessage(data.content, data.model, data.reasoning);
                break;

            case 'response':
                // Streaming partial response
                break;

            case 'error':
                this.setProcessing(false);
                this.addErrorMessage(data.content);
                break;

            default:
                console.log('Unknown message type:', data.type, data);
        }
    }

    sendMessage() {
        const message = this.inputEl.value.trim();
        if (!message || this.isProcessing || !this.isConnected) return;

        // Add user message to chat
        this.addUserMessage(message);

        // Send via WebSocket
        this.ws.send(JSON.stringify({
            message: message,
            mode: this.currentMode,
        }));

        // Clear input
        this.inputEl.value = '';
        this.inputEl.style.height = 'auto';
        this.charCount.textContent = '0';
    }

    // UI Updates
    setMode(mode) {
        this.currentMode = mode;
        document.querySelectorAll('.mode-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.mode === mode);
        });
        const labels = { chat: 'Chat Mode', plan: 'Plan Mode', build: 'Build Mode' };
        this.modeLabel.textContent = labels[mode] || 'Chat Mode';

        const placeholders = {
            chat: 'Type your message...',
            plan: 'Describe what you want to plan...',
            build: 'Describe what you want to build...',
        };
        this.inputEl.placeholder = placeholders[mode] || 'Type your message...';
    }

    setProcessing(processing) {
        this.isProcessing = processing;
        this.sendBtn.disabled = processing;
        this.thinkingIndicator.classList.toggle('hidden', !processing);
        if (!processing) {
            this.thinkingText.textContent = 'Thinking...';
        }
    }

    updateThinking(text) {
        this.thinkingText.textContent = text;
    }

    scrollToBottom() {
        if (this.autoScroll) {
            const container = document.getElementById('chat-container');
            container.scrollTop = container.scrollHeight;
        }
    }

    // Message Rendering
    addUserMessage(content) {
        const html = `
            <div class="message user-message">
                <div class="message-avatar">U</div>
                <div class="message-body">
                    <div class="message-header">
                        <span class="message-sender">You</span>
                        <span>${this.timeStr()}</span>
                    </div>
                    <div class="message-content">${this.escapeHtml(content)}</div>
                </div>
            </div>
        `;
        this.messagesEl.insertAdjacentHTML('beforeend', html);
        this.scrollToBottom();
    }

    addAssistantMessage(content, model, reasoning) {
        const formattedContent = this.formatContent(content);
        const modelBadge = model ? `<span style="color: var(--purple); font-size: 10px; background: var(--bg-tertiary); padding: 1px 6px; border-radius: 10px;">${model}</span>` : '';

        const html = `
            <div class="message assistant-message">
                <div class="message-avatar">N</div>
                <div class="message-body">
                    <div class="message-header">
                        <span class="message-sender">Nexus</span>
                        ${modelBadge}
                        <span>${this.timeStr()}</span>
                    </div>
                    <div class="message-content">${formattedContent}</div>
                </div>
            </div>
        `;
        this.messagesEl.insertAdjacentHTML('beforeend', html);

        // Add reasoning toggle if available
        if (reasoning && reasoning.thoughts && reasoning.thoughts.length > 0) {
            const reasoningHtml = this.renderReasoning(reasoning);
            this.messagesEl.insertAdjacentHTML('beforeend', reasoningHtml);
        }

        this.scrollToBottom();
    }

    addThinkingMessage(content) {
        // Remove previous thinking message to avoid flooding
        const existing = this.messagesEl.querySelectorAll('.thinking-message');
        if (existing.length > 5) {
            existing[0].remove();
        }

        const html = `
            <div class="thinking-message" style="${this.showThinking ? '' : 'display:none'}">
                <div class="message-content">${this.escapeHtml(content)}</div>
            </div>
        `;
        this.messagesEl.insertAdjacentHTML('beforeend', html);
        this.scrollToBottom();
    }

    addToolCallMessage(toolName, metadata) {
        const argsStr = metadata ? JSON.stringify(metadata, null, 2) : '';
        const html = `
            <div class="tool-message" style="${this.showThinking ? '' : 'display:none'}">
                <span class="tool-name">⚡ ${this.escapeHtml(toolName)}</span>
                ${argsStr ? `<pre style="margin-top:4px;font-size:11px;color:var(--text-muted);max-height:60px;overflow:hidden;">${this.escapeHtml(argsStr)}</pre>` : ''}
            </div>
        `;
        this.messagesEl.insertAdjacentHTML('beforeend', html);
        this.scrollToBottom();
    }

    addToolResultMessage(content, metadata) {
        const toolName = metadata?.tool || 'tool';
        const truncated = content.length > 200 ? content.substring(0, 200) + '...' : content;
        const html = `
            <div class="tool-message" style="${this.showThinking ? '' : 'display:none'}">
                <span style="color: var(--green); font-size: 11px;">✓ ${this.escapeHtml(toolName)} result:</span>
                <div class="tool-result">${this.escapeHtml(truncated)}</div>
            </div>
        `;
        this.messagesEl.insertAdjacentHTML('beforeend', html);
        this.scrollToBottom();
    }

    addSystemMessage(content) {
        const html = `
            <div class="message system-message">
                <div class="message-content">
                    <p>${content}</p>
                </div>
            </div>
        `;
        this.messagesEl.insertAdjacentHTML('beforeend', html);
        this.scrollToBottom();
    }

    addErrorMessage(content) {
        const html = `
            <div class="message system-message">
                <div class="message-content" style="color: var(--red);">
                    <p>Error: ${this.escapeHtml(content)}</p>
                </div>
            </div>
        `;
        this.messagesEl.insertAdjacentHTML('beforeend', html);
        this.scrollToBottom();
    }

    renderReasoning(reasoning) {
        const thoughts = reasoning.thoughts || [];
        const duration = reasoning.duration ? reasoning.duration.toFixed(1) : '?';
        const thoughtsHtml = thoughts.map(t => {
            const icons = {
                observation: '👁', analysis: '🔍', hypothesis: '💡',
                plan: '📋', action: '⚡', result: '📊',
                reflection: '🪞', conclusion: '✅', error: '❌'
            };
            const icon = icons[t.type] || '💭';
            return `<div style="padding:2px 0;"><span>${icon}</span> <strong>${t.type}:</strong> ${this.escapeHtml(t.content)}</div>`;
        }).join('');

        return `
            <div class="thinking-toggle" onclick="this.nextElementSibling.classList.toggle('hidden')" style="${this.showThinking ? '' : 'display:none'}">
                ▶ Reasoning (${thoughts.length} steps, ${duration}s)
            </div>
            <div class="thinking-message hidden" style="font-size:12px;">
                <div class="message-content" style="font-style:normal;">${thoughtsHtml}</div>
            </div>
        `;
    }

    // Plan Display
    showPlan(content, metadata) {
        this.planPanel.classList.remove('hidden');
        this.planContent.textContent = content;
        if (metadata && metadata.progress !== undefined) {
            this.planProgressBar.style.width = (metadata.progress * 100) + '%';
        }
    }

    updatePlanStep(data) {
        if (data.metadata && data.metadata.step !== undefined) {
            // Update plan display
            const content = this.planContent.textContent;
            this.planContent.textContent = content + '\n' + data.content;
        }
    }

    // Content Formatting
    formatContent(text) {
        if (!text) return '';

        // Escape HTML first
        let html = this.escapeHtml(text);

        // Code blocks (```)
        html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
            return `<pre><code class="language-${lang}">${code.trim()}</code></pre>`;
        });

        // Inline code
        html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

        // Bold
        html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

        // Italic
        html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');

        // Line breaks
        html = html.replace(/\n/g, '<br>');

        return html;
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    timeStr() {
        return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }

    // API Calls
    async loadStatus() {
        try {
            const resp = await this.authFetch('/api/status');
            const data = await resp.json();

            document.getElementById('ollama-status').className =
                'status-dot ' + (data.ollama ? 'online' : 'offline');
            document.getElementById('memory-status').className =
                'status-dot ' + (data.memory ? 'online' : 'offline');
            document.getElementById('db-status').className =
                'status-dot ' + (data.database ? 'online' : 'offline');

        } catch (e) {
            console.error('Failed to load status:', e);
        }
    }

    async loadModels() {
        try {
            const resp = await this.authFetch('/api/models');
            const data = await resp.json();

            this.modelSelect.innerHTML = '';
            if (data.models && data.models.length > 0) {
                data.models.forEach(model => {
                    const opt = document.createElement('option');
                    opt.value = model.name;
                    opt.textContent = model.name;
                    if (model.name === data.current) {
                        opt.selected = true;
                    }
                    this.modelSelect.appendChild(opt);
                });
                this.modelInfo.textContent = `${data.models.length} models available`;
            } else {
                const opt = document.createElement('option');
                opt.value = '';
                opt.textContent = 'No models found';
                this.modelSelect.appendChild(opt);
                this.modelInfo.textContent = 'Connect Ollama to load models';
            }
        } catch (e) {
            this.modelSelect.innerHTML = '<option value="">Connection error</option>';
            this.modelInfo.textContent = 'Could not reach server';
        }
    }

    async switchModel() {
        const model = this.modelSelect.value;
        if (!model) return;

        try {
            await this.authFetch('/api/model', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ model }),
            });
            this.addSystemMessage(`Switched to model: ${model}`);
        } catch (e) {
            this.addErrorMessage('Failed to switch model');
        }
    }

    async loadMCPStatus() {
        try {
            const resp = await this.authFetch('/api/mcp/status');
            const data = await resp.json();

            this.mcpPanel.innerHTML = '';
            const entries = Object.entries(data);

            if (entries.length === 0) {
                this.mcpPanel.innerHTML = '<div class="info-text">No MCPs configured</div>';
                return;
            }

            entries.forEach(([name, info]) => {
                const dotClass = info.connected ? 'online' : (info.enabled ? 'offline' : 'warning');
                const toolsText = info.connected ? `${info.tools_count} tools` : (info.enabled ? 'offline' : 'disabled');
                const html = `
                    <div class="mcp-item">
                        <span class="status-dot ${dotClass}"></span>
                        <span class="mcp-name" title="${info.description || name}">${name}</span>
                        <span class="mcp-tools">${toolsText}</span>
                    </div>
                `;
                this.mcpPanel.insertAdjacentHTML('beforeend', html);
            });
        } catch (e) {
            this.mcpPanel.innerHTML = '<div class="info-text">Could not load MCP status</div>';
        }
    }

    async reloadMCP() {
        try {
            this.addSystemMessage('Reloading MCP configuration...');
            const resp = await this.authFetch('/api/mcp/reload', { method: 'POST' });
            const data = await resp.json();
            await this.loadMCPStatus();
            this.addSystemMessage('MCP configuration reloaded.');
        } catch (e) {
            this.addErrorMessage('Failed to reload MCP configuration');
        }
    }
}

// Initialize the app
document.addEventListener('DOMContentLoaded', () => {
    window.nexus = new NexusApp();
});
