# ASTRA AI Assistant

> Reduce friction. Increase momentum. Compound intelligence.

**Repo:** [Fxprogrammer69/astra-ai-assistant](https://github.com/Fxprogrammer69/astra-ai-assistant)

A futuristic AI-powered desktop app with Claude API brain, local Ollama LLM,
Whisper speech-to-text (no wake word), MediaPipe gesture control, webcam
presence detection, and screen awareness.

### Pathing fix (Windows)

Launch scripts use `%~dp0` so they work whether ASTRA lives on classic Desktop
or OneDrive Desktop. Double-click `ASTRA.bat` from the project folder, or use
the Desktop launcher that points at this repo.

---

## Stack

| Layer | Technology |
|---|---|
| Desktop shell | Electron 28 |
| UI | HTML/CSS/JS (custom dark UI) |
| AI brain (cloud) | Claude API (claude-sonnet-4) |
| AI brain (local) | Ollama — llama3.1:8b |
| Speech (STT) | OpenAI Whisper (local, no wake word) |
| Gestures + CV | MediaPipe Hands + Face Detection |
| Screen awareness | Pillow + Claude Vision API |
| Memory | SQLite-backed JSON |
| Webhooks | Python HTTP server (port 9003) |
| Desktop ↔ Brain | stdin/stdout JSON + WebSocket |

---

## Quick Start

### 1. Prerequisites

- Python 3.9+  → https://python.org
- Node.js 18+  → https://nodejs.org
- Ollama (optional but recommended) → https://ollama.ai

### 2. Run Setup

```bash
python setup.py
```

This will:
- Install all Python dependencies (Whisper, MediaPipe, OpenCV, etc.)
- Install Node.js dependencies
- Create `.env` with your API key
- Pull Ollama model
- Create launch scripts for your OS
- Create a desktop shortcut

### 3. Launch

**Windows:**
```
Double-click ASTRA.bat
```

**macOS / Linux:**
```bash
./astra.sh
```

**Or manually:**
```bash
npm start
```

---

## Gesture Reference

| Gesture | Action |
|---|---|
| ✊ Fist | Activate Focus Lock |
| 🖐 Open Hand | Switch Mode |
| ✌ Peace | Start Deep Work Timer |
| 👍 Thumbs Up | Confirm |
| ☝ Point Up | Scroll Up |
| 👇 Point Down | Scroll Down |

Hold gesture for ~5 frames (~0.15s) to trigger.

---

## Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `Alt + Space` | Push-to-talk (no wake word) |
| `Ctrl+Shift+A` | Quick open / hide ASTRA |
| `Ctrl+Shift+F` | Activate Focus Lock |
| `Enter` | Send message |

---

## Modes

| Mode | Focus |
|---|---|
| Engineer | Coding, debugging, architecture |
| Student | Study blocks, revision, JEE prep |
| Founder | Startup execution, research, product |
| Focus Lock | All distractions blocked, timer active |
| Trading | Market feeds, journal, alerts |
| Recovery | Low cognitive load, rest |

---

## Webhook Endpoints

ASTRA runs a webhook server on `http://localhost:9003`

| Endpoint | Source |
|---|---|
| `POST /github` | GitHub push, PR, deploy events |
| `POST /stripe` | Stripe payment events |
| `POST /discord` | Discord bot messages |
| `POST /notion` | Notion page updates |
| `POST /vercel` | Vercel deployment status |
| `POST /trading` | TradingView alerts |
| `POST /custom/*` | Any custom trigger |
| `GET /health` | Health check |

---

## Mobile Companion

The mobile companion app (React Native) connects to ASTRA desktop
via WebSocket on port 9001.

```bash
cd mobile
npm install
npx expo start
```

Set `ASTRA_HOST` in `mobile/.env` to your desktop's local IP.

---

## Environment Variables (.env)

```env
ANTHROPIC_API_KEY=sk-ant-...
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1:8b
WHISPER_MODEL=tiny
```

---

## Building Installers

```bash
# Windows (.exe installer)
npm run build:win

# macOS (.dmg)
npm run build:mac

# Linux (.AppImage)
npm run build:linux
```

Output goes to `/dist` folder.

---

## Manual Python Dependency Install

If setup.py fails for any package:

```bash
pip install anthropic
pip install openai-whisper
pip install mediapipe
pip install opencv-python
pip install sounddevice numpy
pip install Pillow
pip install websockets
```

---

## Troubleshooting

**Webcam not detected**
→ Allow camera permissions. Check `cv2.VideoCapture(0)` — try index 1 or 2.

**Whisper slow**
→ Use `tiny` model in Settings. GPU acceleration requires `torch` with CUDA.

**Ollama not responding**
→ Run `ollama serve` in a separate terminal before launching ASTRA.

**Claude API errors**
→ Check API key in Settings. Verify at https://console.anthropic.com

**Gestures not registering**
→ Ensure good lighting. Raise gesture confidence threshold in Settings.

---

## Project Structure

```
astra/
├── src/
│   ├── main/
│   │   ├── index.js          # Electron main process
│   │   └── preload.js        # Secure IPC bridge
│   ├── renderer/
│   │   ├── index.html        # UI
│   │   ├── style.css         # Futuristic dark theme
│   │   └── app.js            # UI logic + event handling
│   ├── brain/
│   │   └── server.py         # Python brain (NLP+CV+Speech)
│   ├── memory/
│   │   └── memory.py         # Persistent memory layer
│   └── webhooks/
│       └── engine.py         # Webhook server
├── mobile/                   # React Native companion app
├── models/
│   └── memory.json           # Auto-generated memory store
├── assets/                   # Icons
├── setup.py                  # One-command setup
├── requirements.txt          # Python deps
├── package.json              # Node deps + build config
└── .env                      # API keys (git-ignored)
```
