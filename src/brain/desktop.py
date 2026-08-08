#!/usr/bin/env python3
"""
ASTRA Desktop — runs 100% on YOUR PC (localhost only).
Opens a native desktop window (not Chrome, not the internet).

  py -3 src/brain/desktop.py
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "src" / "brain"))
sys.path.insert(0, str(ROOT / "src"))

# Force local-only bind
os.environ.setdefault("ASTRA_HOST", "127.0.0.1")
os.environ.setdefault("ASTRA_FAST_MODE", "1")
os.environ.setdefault("ASTRA_ENABLE_CV", "0")
os.environ.setdefault("ASTRA_ENABLE_SPEECH", "0")

import webapp  # noqa: E402


def main():
    # Never open an external browser — desktop window only
    sys.argv = [sys.argv[0], "--no-browser"]

    # Parse ports the same way webapp does
    host = os.environ.get("ASTRA_HOST", "127.0.0.1")
    http_port = int(os.environ.get("ASTRA_PORT", "8787"))
    ws_port = int(os.environ.get("ASTRA_WS_PORT", "8788"))
    webapp._Ports.http = http_port
    webapp._Ports.ws = ws_port

    print("=" * 50, flush=True)
    print("  ASTRA DESKTOP — LOCAL ONLY", flush=True)
    print("  Runs on this PC only (127.0.0.1)", flush=True)
    print("  Not uploaded. Not hosted online.", flush=True)
    print("=" * 50, flush=True)
    print("Booting local brain…", flush=True)

    brain = webapp.WebBrain()
    webapp.start_http()

    # Start WebSocket server in background thread
    def _ws():
        import asyncio
        asyncio.run(webapp.run_ws(brain))

    t = threading.Thread(target=_ws, daemon=True)
    t.start()

    # Wait until HTTP is up
    url = f"http://{host}:{http_port}/"
    for _ in range(40):
        try:
            import urllib.request
            with urllib.request.urlopen(url + "api/health", timeout=0.5) as r:
                if r.status == 200:
                    break
        except Exception:
            time.sleep(0.25)

    print(f"Local UI ready at {url}", flush=True)
    print("Opening desktop window…", flush=True)

    try:
        import webview
    except ImportError:
        print("pywebview missing — installing…", flush=True)
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pywebview", "-q"])
        import webview

    # Native OS window pointing at local server (WebView2 on Windows)
    window = webview.create_window(
        title="ASTRA",
        url=url,
        width=1280,
        height=820,
        min_size=(900, 600),
        background_color="#07060b",
        text_select=True,
    )
    webview.start(debug=False)
    print("ASTRA desktop window closed.", flush=True)


if __name__ == "__main__":
    main()
