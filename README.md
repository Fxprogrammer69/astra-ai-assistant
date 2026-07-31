# ASTRA AI Assistant

Autonomous desktop intelligence: **Electron shell** + **Python brain** + **Grok (xAI)** + **agent tools** + **webhooks**.

**Repo:** https://github.com/Fxprogrammer69/astra-ai-assistant

## Features

| Area | Capability |
|------|------------|
| Chat | Streaming replies, Grok / Ollama / local tools |
| Agent | `list_dir`, `read_file`, `write_file`, allowlisted `run_shell`, `system_info` |
| Missions | One-click workflows (system scan, desktop inventory, git status, focus prep, webhooks) |
| Memory | Notes, facts, goals, audit trail (`models/memory.json`) |
| Webhooks | HTTP server on **:9003** (`/health`, `/github`, `/astra`, …) |
| Health | Subsystem probe panel |
| CV / Speech | MediaPipe + Whisper when installed (lazy load) |

## Quick start (Windows)

```bat
cd C:\Users\royru\OneDrive\Desktop\Astra-Desktop
npm install
npm start
```

Or double-click **ASTRA.bat** on the Desktop.

### Grok (xAI)

1. Credits: https://console.x.ai  
2. Put key in `.env` (gitignored):

```env
XAI_API_KEY=xai-...
XAI_BASE_URL=https://api.x.ai/v1
XAI_MODEL=grok-4.5
```

Without credits, ASTRA still runs **local agent tools** and missions.

### Optional

```bash
pip install -r requirements.txt   # Whisper, MediaPipe, etc.
ollama serve                      # local LLM fallback
```

## Build installer

```bash
npm run build:win
```

Output: `dist/`

## Keyboard

| Shortcut | Action |
|----------|--------|
| Alt+Space | Push-to-talk |
| Ctrl+Shift+A | Show / hide |
| Ctrl+Shift+F | Focus Lock |

## Project layout

```
src/main/       Electron main + preload
src/renderer/   UI
src/brain/      Python brain, agent, tools, missions
src/webhooks/   HTTP webhook engine
models/         memory.json (runtime)
```
