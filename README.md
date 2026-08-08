# ASTRA AI Assistant

**Web-first** desktop intelligence: **Python brain** + **browser UI** (no Electron required) + local-first LLM (Ollama → NVIDIA) + **RAG memory** + **MCP connectors** + voice STT.

**Repo:** https://github.com/Fxprogrammer69/astra-ai-assistant

## Quick start (Windows)

```bat
cd C:\Users\royru\OneDrive\Desktop\Astra-Desktop
pip install -r requirements.txt
ollama serve
ollama pull llama3.2:3b
ASTRA.bat
```

Opens **http://127.0.0.1:8787** in your browser. Brain WebSocket: **ws://127.0.0.1:8788**.

Or:

```bash
py -3 src/brain/webapp.py
```

### Ports

| Port | Service |
|------|---------|
| **8787** | HTTP UI |
| **8788** | Brain WebSocket |
| **9003** | Webhooks |

## Features

| Area | Capability |
|------|------------|
| Chat | Local-first: Ollama → NVIDIA NIM → Claude; streaming |
| RAG | Every turn stored; retrieve + continual learning; import other AI chats |
| Voice | Mic → WAV → Whisper / SpeechRecognition (real browser, not Electron) |
| MCP | External connectors via `models/mcp.json` |
| Agent | Allowlisted tools + missions |
| Memory | Notes, facts, goals, training pairs for future fine-tunes |

## Configuration (`.env`)

```env
# Local-first routing
ASTRA_ROUTE=auto
OLLAMA_MODEL=llama3.2:3b

# Cloud fallback
NVIDIA_NIM_API_KEY=nvapi-...
NVIDIA_MODEL=meta/llama-3.2-3b-instruct

ASTRA_FAST_MODE=1
ASTRA_MAX_TOKENS=256
```

## MCP connectors

Edit `models/mcp.json`, set `"enabled": true`, add API keys in `env`, then **Settings → Reload MCP**.

## Legacy Electron

Electron is **optional / legacy**:

```bash
npm install
npm run electron:legacy
```

Prefer web mode for voice reliability and lower RAM.

## Project layout

```
src/brain/     Python brain, webapp, RAG, MCP, agent
src/renderer/  Browser UI (astra-bridge.js replaces Electron preload)
models/        memory, rag, mcp.json, training pairs
ASTRA.bat      Web launcher
```
