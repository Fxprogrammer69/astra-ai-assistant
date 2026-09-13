# ASTRA AI Assistant

**Local desktop app on your PC only** (binds to `127.0.0.1` — not the public internet).

Python brain + native desktop window (pywebview / WebView2) + local-first LLM (Ollama → NVIDIA / Grok / Claude) + SQLite memory + MCP + voice.

**Repo:** https://github.com/Fxprogrammer69/astra-ai-assistant

## Quick start (Windows)

```bat
cd path\to\astra-ai-assistant
pip install -r requirements.txt
ollama serve
ollama pull llama3.2:3b
ollama pull nomic-embed-text
ASTRA.bat
```

Double-click **ASTRA.bat** → opens an **ASTRA desktop window** on your machine.

Nothing is hosted online. Traffic stays on localhost.

Or:

```bash
py -3 src/brain/desktop.py
```

### Ports (localhost only)

| Port | Service |
|------|---------|
| **8787** | Local UI (served on this PC) |
| **8788** | Local brain WebSocket |
| **9003** | Local webhooks (`127.0.0.1`) |

## Features

| Area | Capability |
|------|------------|
| Chat | Local-first: Ollama → NVIDIA NIM / Grok / Claude; streaming |
| Memory | Unified SQLite (`models/astra.db`) — turns, facts, notes, goals, tasks |
| RAG | Ollama embeddings when available (`nomic-embed-text`), else hashed fallback |
| Voice | Mic → WAV → faster-whisper / Whisper / SpeechRecognition |
| MCP | External connectors via `models/mcp.json` |
| Agent | Allowlisted tools + missions |
| Tasks | Persisted in SQLite (not demo HTML) |
| Markets | Live BTC/ETH (CoinGecko) + Gold/Nifty (Yahoo, best-effort) |
| Stats | Real CPU/RAM via `psutil` |

## Configuration (`.env`)

```env
# Local-first routing
ASTRA_ROUTE=auto
OLLAMA_MODEL=llama3.2:3b
OLLAMA_EMBED_MODEL=nomic-embed-text

# Cloud fallback
NVIDIA_NIM_API_KEY=nvapi-...
NVIDIA_MODEL=meta/llama-3.2-3b-instruct
XAI_API_KEY=xai-...
ANTHROPIC_API_KEY=sk-ant-...

ASTRA_FAST_MODE=1
ASTRA_MAX_TOKENS=256

# Optional: verify GitHub webhooks
GITHUB_WEBHOOK_SECRET=
ASTRA_WEBHOOK_HOST=127.0.0.1
```

## MCP connectors

Edit `models/mcp.json`, set `"enabled": true`, add API keys in `env`, then **Settings → Reload MCP**. Paths expand `%USERPROFILE%` and `~`.

## Legacy Electron

Electron is **optional / legacy** (`src/main/`):

```bash
npm install
npm run electron:legacy
```

Prefer web/desktop mode for voice reliability and lower RAM.

## Project layout

```
src/brain/     Python brain, webapp, RAG, store, MCP, agent
src/renderer/  Browser UI (astra-bridge.js)
models/        astra.db, mcp.json
ASTRA.bat      Desktop launcher
```
