#!/usr/bin/env python3
"""
ASTRA Web shell — no Electron.
Serves the UI over HTTP and talks to the brain over WebSocket.

  py -3 src/brain/webapp.py
  → http://127.0.0.1:8787
"""
from __future__ import annotations

import argparse
import asyncio
import json
import mimetypes
import os
import queue
import sys
import threading
import time
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Set

# Paths
ROOT = Path(__file__).resolve().parent.parent.parent
RENDERER = ROOT / "src" / "renderer"
os.chdir(ROOT)

# Ensure imports
sys.path.insert(0, str(ROOT / "src" / "brain"))
sys.path.insert(0, str(ROOT / "src"))

# Load .env before importing brain CONFIG
def _load_dotenv():
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    try:
        for line in env_path.read_text(encoding="utf-8-sig").splitlines():
            t = line.strip()
            if not t or t.startswith("#") or "=" not in t:
                continue
            k, v = t.split("=", 1)
            k, v = k.strip().lstrip("\ufeff"), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v
    except Exception:
        pass

_load_dotenv()
os.environ.setdefault("ASTRA_FAST_MODE", "1")
os.environ.setdefault("ASTRA_ENABLE_CV", "0")
os.environ.setdefault("ASTRA_ENABLE_SPEECH", "0")

from server import ASTRABrain  # noqa: E402

HOST = os.environ.get("ASTRA_HOST", "127.0.0.1")
HTTP_PORT = int(os.environ.get("ASTRA_PORT", "8787"))
WS_PORT = int(os.environ.get("ASTRA_WS_PORT", "8788"))


class _Ports:
    http = HTTP_PORT
    ws = WS_PORT


class WebBrain(ASTRABrain):
    """Brain that fans emit() out to browser WebSocket clients."""

    def __init__(self):
        self._client_queues: Set[queue.Queue] = set()
        self._q_lock = threading.Lock()
        super().__init__()

    def register_client(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=500)
        with self._q_lock:
            self._client_queues.add(q)
        return q

    def unregister_client(self, q: queue.Queue):
        with self._q_lock:
            self._client_queues.discard(q)

    def emit(self, event: dict):
        try:
            msg = json.dumps(event, ensure_ascii=False)
        except Exception:
            msg = json.dumps({"type": "error", "msg": "emit serialize failed"})
        # Keep stdout for logs
        try:
            print(msg, flush=True)
        except Exception:
            pass
        with self._q_lock:
            dead = []
            for q in self._client_queues:
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                self._client_queues.discard(q)


class StaticHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(RENDERER), **kwargs)

    def log_message(self, fmt, *args):
        # quieter
        if args and str(args[0]).startswith("\"GET /"):
            return
        try:
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))
        except Exception:
            pass

    def end_headers(self):
        # Dev-friendly CORS for same-machine tools
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def do_GET(self):
        if self.path in ("/", ""):
            self.path = "/index.html"
        elif self.path.startswith("/api/health"):
            body = json.dumps({"ok": True, "mode": "web", "ws": f"ws://{HOST}:{WS_PORT}"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        return super().do_GET()


def start_http():
    httpd = ThreadingHTTPServer((HOST, _Ports.http), StaticHandler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd


async def ws_handler(websocket, brain: WebBrain):
    q = brain.register_client()
    # Greeting
    try:
        await websocket.send(json.dumps({
            "type": "brain_status",
            "status": "online",
            "detail": "web mode",
            "mode": "web",
        }))
    except Exception:
        pass

    async def reader():
        async for raw in websocket:
            try:
                data = json.loads(raw)
            except Exception:
                await websocket.send(json.dumps({"type": "error", "msg": "invalid JSON"}))
                continue
            # Offload blocking brain work
            await asyncio.to_thread(brain.handle_input, data)

    async def writer():
        while True:
            try:
                msg = await asyncio.to_thread(q.get, True, 0.5)
            except queue.Empty:
                # ping keepalive
                try:
                    await websocket.ping()
                except Exception:
                    break
                continue
            try:
                await websocket.send(msg)
            except Exception:
                break

    try:
        await asyncio.gather(reader(), writer())
    except Exception:
        pass
    finally:
        brain.unregister_client(q)


async def run_ws(brain: WebBrain):
    try:
        # websockets 12+ / 16
        try:
            from websockets.asyncio.server import serve
        except ImportError:
            from websockets.server import serve  # type: ignore
    except ImportError:
        print("ERROR: websockets package required. pip install websockets", flush=True)
        raise

    async def _handler(websocket):
        await ws_handler(websocket, brain)

    async with serve(
        _handler,
        HOST,
        _Ports.ws,
        ping_interval=20,
        ping_timeout=20,
        max_size=20 * 1024 * 1024,  # large audio payloads
    ):
        print(json.dumps({
            "type": "web_ready",
            "http": f"http://{HOST}:{_Ports.http}",
            "ws": f"ws://{HOST}:{_Ports.ws}",
        }), flush=True)
        await asyncio.Future()  # run forever


def main():
    parser = argparse.ArgumentParser(description="ASTRA web shell (no Electron)")
    parser.add_argument("--no-browser", action="store_true", help="Do not auto-open browser")
    parser.add_argument("--port", type=int, default=HTTP_PORT)
    parser.add_argument("--ws-port", type=int, default=WS_PORT)
    args = parser.parse_args()

    _Ports.http = args.port
    _Ports.ws = args.ws_port

    print(f"ASTRA web starting… UI http://{HOST}:{_Ports.http}  WS ws://{HOST}:{_Ports.ws}", flush=True)
    print("Booting brain (RAG / MCP / local-first)…", flush=True)
    brain = WebBrain()
    start_http()

    url = f"http://{HOST}:{_Ports.http}/"
    if not args.no_browser:
        # slight delay so server is up
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()

    try:
        asyncio.run(run_ws(brain))
    except KeyboardInterrupt:
        print("\nASTRA stopped.", flush=True)


if __name__ == "__main__":
    main()
