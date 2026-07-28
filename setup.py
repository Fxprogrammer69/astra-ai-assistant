#!/usr/bin/env python3
"""
ASTRA Setup Script
Supports: Windows, macOS, Linux
Run: python setup.py
"""

import os
import sys
import subprocess
import platform
import shutil
from pathlib import Path

OS = platform.system()  # Windows | Darwin | Linux
ROOT = Path(__file__).parent

CYAN  = "\033[96m"
GREEN = "\033[92m"
WARN  = "\033[93m"
RED   = "\033[91m"
BOLD  = "\033[1m"
RESET = "\033[0m"

def p(msg, color=CYAN):   print(f"{color}{msg}{RESET}")
def ok(msg):              print(f"{GREEN}  ✓ {msg}{RESET}")
def warn(msg):            print(f"{WARN}  ⚠ {msg}{RESET}")
def err(msg):             print(f"{RED}  ✗ {msg}{RESET}")
def header(msg):          print(f"\n{BOLD}{CYAN}{'─'*50}\n  {msg}\n{'─'*50}{RESET}")

def run(cmd, check=True, capture=False):
    kwargs = dict(shell=True, check=check)
    if capture:
        kwargs["capture_output"] = True
        kwargs["text"] = True
    return subprocess.run(cmd, **kwargs)

def check_python():
    header("Checking Python")
    v = sys.version_info
    if v.major < 3 or (v.major == 3 and v.minor < 9):
        err(f"Python 3.9+ required. Found: {v.major}.{v.minor}")
        err("Download from https://python.org")
        sys.exit(1)
    ok(f"Python {v.major}.{v.minor}.{v.micro}")

def check_node():
    header("Checking Node.js")
    if shutil.which("node"):
        r = run("node --version", capture=True, check=False)
        ok(f"Node.js {r.stdout.strip()}")
    else:
        err("Node.js not found.")
        warn("Download from https://nodejs.org (LTS version)")
        if OS == "Darwin":
            warn("Or run: brew install node")
        elif OS == "Linux":
            warn("Or run: sudo apt install nodejs npm")
        sys.exit(1)

def install_python_deps():
    header("Installing Python Dependencies")
    p("Installing core packages...")
    pkgs = [
        "anthropic",
        "websockets",
        "Pillow",
        "numpy",
    ]
    for pkg in pkgs:
        r = run(f"{sys.executable} -m pip install {pkg} -q", check=False)
        if r.returncode == 0:
            ok(pkg)
        else:
            warn(f"{pkg} — failed, continuing")

    p("\nInstalling CV + Speech packages (may take a few minutes)...")
    heavy_pkgs = {
        "openai-whisper": "Whisper STT (speech-to-text)",
        "mediapipe":      "MediaPipe (gestures + presence)",
        "opencv-python":  "OpenCV (webcam processing)",
        "sounddevice":    "SoundDevice (microphone input)",
    }
    for pkg, desc in heavy_pkgs.items():
        p(f"  Installing {desc}...")
        r = run(f"{sys.executable} -m pip install {pkg} -q", check=False)
        if r.returncode == 0:
            ok(f"{desc}")
        else:
            warn(f"{desc} — failed. App will run without it. Install manually: pip install {pkg}")

def install_node_deps():
    header("Installing Node.js Dependencies")
    p("Running npm install...")
    r = run(f"cd \"{ROOT}\" && npm install", check=False)
    if r.returncode == 0:
        ok("Node modules installed")
    else:
        err("npm install failed. Check Node.js installation.")
        sys.exit(1)

def setup_env():
    header("Environment Configuration")
    env_path = ROOT / ".env"
    if env_path.exists():
        ok(".env already exists — skipping")
        return

    print(f"\n{BOLD}Enter your Anthropic API key{RESET} (or press Enter to skip):")
    print(f"{CYAN}Get one at: https://console.anthropic.com{RESET}")
    api_key = input("  API Key: ").strip()

    env_content = f"""# ASTRA Environment Configuration
ANTHROPIC_API_KEY={api_key}
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1:8b
WHISPER_MODEL=tiny
"""
    with open(env_path, "w") as f:
        f.write(env_content)
    ok(".env created")

    if api_key:
        ok("Anthropic API key saved")
    else:
        warn("No API key — ASTRA will use Ollama (local) only")
        warn("Add your key later in Settings → API Keys")

def setup_ollama():
    header("Ollama (Local LLM)")
    if shutil.which("ollama"):
        ok("Ollama already installed")
        p("Pulling recommended model: llama3.1:8b (may take a while)...")
        r = run("ollama pull llama3.1:8b", check=False)
        if r.returncode == 0:
            ok("llama3.1:8b ready")
        else:
            warn("Model pull failed — run manually: ollama pull llama3.1:8b")
    else:
        warn("Ollama not installed")
        if OS == "Darwin":
            warn("Install: brew install ollama  OR  https://ollama.ai")
        elif OS == "Windows":
            warn("Download installer: https://ollama.ai/download/windows")
        elif OS == "Linux":
            warn("Install: curl -fsSL https://ollama.ai/install.sh | sh")
        warn("ASTRA will use Claude API only until Ollama is installed")

def create_launch_scripts():
    header("Creating Launch Scripts")

    if OS == "Windows":
        bat = ROOT / "ASTRA.bat"
        bat.write_text("""@echo off
title ASTRA
cd /d "%~dp0"
echo Starting ASTRA...
if not exist "node_modules\\electron" (
  echo Dependencies missing. Running npm install...
  call npm install
)
set PYTHONPATH=%~dp0src\\brain
call npm start
if errorlevel 1 pause
""")
        ok("ASTRA.bat created (portable %~dp0 paths)")

        dev_bat = ROOT / "ASTRA-dev.bat"
        dev_bat.write_text("""@echo off
title ASTRA (dev)
cd /d "%~dp0"
echo Starting ASTRA (dev mode)...
set PYTHONPATH=%~dp0src\\brain
call npm run dev
""")
        ok("ASTRA-dev.bat created")

    else:
        sh = ROOT / "astra.sh"
        sh.write_text(f"""#!/bin/bash
echo "Starting ASTRA..."
cd "{ROOT}"
export PYTHONPATH="{ROOT}/src/brain"
# Load .env
if [ -f .env ]; then export $(cat .env | xargs); fi
npm start
""")
        sh.chmod(0o755)
        ok("astra.sh created")

        dev_sh = ROOT / "astra-dev.sh"
        dev_sh.write_text(f"""#!/bin/bash
echo "Starting ASTRA (dev mode)..."
cd "{ROOT}"
if [ -f .env ]; then export $(cat .env | xargs); fi
python src/brain/server.py &
BRAIN_PID=$!
npm run dev
kill $BRAIN_PID 2>/dev/null
""")
        dev_sh.chmod(0o755)
        ok("astra-dev.sh created")

def resolve_desktop():
    """Prefer OneDrive Desktop when present (Windows pathing fix)."""
    candidates = [
        Path.home() / "OneDrive" / "Desktop",
        Path.home() / "Desktop",
    ]
    # Also honor Windows USERPROFILE Desktop via shell folders if available
    for d in candidates:
        if d.exists():
            return d
    return Path.home() / "Desktop"

def create_desktop_shortcut():
    header("Desktop Shortcut")
    desktop = resolve_desktop()
    if not desktop.exists():
        warn("Desktop folder not found — skipping shortcut")
        return

    if OS == "Windows":
        try:
            # Portable launcher: always cd into project dir via %~dp0
            launcher = desktop / "ASTRA.bat"
            launcher.write_text(
                f'@echo off\r\n'
                f'title ASTRA\r\n'
                f'cd /d "{ROOT}"\r\n'
                f'call "{ROOT}\\ASTRA.bat"\r\n',
                encoding="utf-8",
            )
            ok(f"Desktop shortcut created: {launcher}")
        except Exception as e:
            warn(f"Could not create Windows shortcut — run ASTRA.bat manually ({e})")

    elif OS == "Darwin":
        app_sh = desktop / "ASTRA.command"
        app_sh.write_text(f"""#!/bin/bash
cd "{ROOT}"
if [ -f .env ]; then export $(cat .env | xargs); fi
npm start
""")
        app_sh.chmod(0o755)
        ok("Desktop shortcut: ASTRA.command")

    elif OS == "Linux":
        desktop_entry = desktop / "ASTRA.desktop"
        launcher = ROOT / "astra.sh"
        desktop_entry.write_text(f"""[Desktop Entry]
Name=ASTRA
Comment=Autonomous Desktop Intelligence System
Exec={launcher}
Icon={ROOT}/assets/icon.png
Terminal=false
Type=Application
Categories=Utility;
""")
        desktop_entry.chmod(0o755)
        ok("Desktop shortcut: ASTRA.desktop")

def verify_setup():
    header("Verification")
    checks = {
        "Python 3.9+":      True,
        "Node.js":          bool(shutil.which("node")),
        "npm":              bool(shutil.which("npm")),
        "node_modules":     (ROOT / "node_modules").exists(),
        "Brain server":     (ROOT / "src" / "brain" / "server.py").exists(),
        "Renderer":         (ROOT / "src" / "renderer" / "index.html").exists(),
        ".env":             (ROOT / ".env").exists(),
        "Ollama":           bool(shutil.which("ollama")),
    }
    all_ok = True
    for name, status in checks.items():
        if status:
            ok(name)
        else:
            warn(f"{name} — not found (optional or install manually)")
            if name in ["Python 3.9+", "Node.js", "npm", "node_modules"]:
                all_ok = False
    return all_ok

def print_summary():
    print(f"""
{BOLD}{CYAN}
╔══════════════════════════════════════════════╗
║           ASTRA SETUP COMPLETE               ║
╚══════════════════════════════════════════════╝{RESET}

{BOLD}To launch ASTRA:{RESET}""")

    if OS == "Windows":
        print(f"  {GREEN}Double-click ASTRA.bat{RESET}  or  {GREEN}npm start{RESET}")
    else:
        print(f"  {GREEN}./astra.sh{RESET}  or  {GREEN}npm start{RESET}")

    print(f"""
{BOLD}First-time checklist:{RESET}
  1. Add Anthropic API key in Settings (if not done)
  2. Run: {GREEN}ollama serve{RESET} in a separate terminal
  3. Allow webcam + microphone permissions when prompted

{BOLD}Keyboard shortcuts:{RESET}
  {CYAN}Alt + Space{RESET}        Push-to-talk (no wake word)
  {CYAN}Ctrl+Shift+A{RESET}       Quick open/hide
  {CYAN}Ctrl+Shift+F{RESET}       Focus Lock

{BOLD}Gesture controls:{RESET}
  ✊ Fist          → Focus Lock
  🖐 Open Hand     → Switch Mode
  ✌  Peace         → Start Deep Work
  👍 Thumbs Up     → Confirm
  ☝  Point Up/Down → Scroll

{CYAN}Docs: https://github.com/Fxprogrammer69/astra-ai-assistant{RESET}
""")

def main():
    print(f"""
{BOLD}{CYAN}
  █████╗ ███████╗████████╗██████╗  █████╗
 ██╔══██╗██╔════╝╚══██╔══╝██╔══██╗██╔══██╗
 ███████║███████╗   ██║   ██████╔╝███████║
 ██╔══██║╚════██║   ██║   ██╔══██╗██╔══██║
 ██║  ██║███████║   ██║   ██║  ██║██║  ██║
 ╚═╝  ╚═╝╚══════╝   ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝
  Autonomous Desktop Intelligence System
  Setup v1.0 — {OS}
{RESET}""")

    check_python()
    check_node()
    install_python_deps()
    install_node_deps()
    setup_env()
    setup_ollama()
    create_launch_scripts()
    create_desktop_shortcut()
    ok_all = verify_setup()
    print_summary()

if __name__ == "__main__":
    main()
