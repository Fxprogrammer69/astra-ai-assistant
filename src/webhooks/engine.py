#!/usr/bin/env python3
"""
ASTRA Webhook Engine
Handles incoming webhooks (GitHub, Stripe, Discord, etc.)
and outgoing triggers (n8n, Zapier, custom endpoints)
Runs as a lightweight HTTP server on port 9003
"""

import json
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import urllib.request
import hashlib
import hmac
import os

WEBHOOK_PORT = 9003

class WebhookHandler(BaseHTTPRequestHandler):
    """Handles incoming webhook POST requests."""

    def log_message(self, format, *args):
        pass  # Suppress default logging

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-GitHub-Event, X-ASTRA-Signature")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            self._respond(200, {
                "status": "ASTRA webhook engine online",
                "port": WEBHOOK_PORT,
                "endpoints": [
                    "GET /health",
                    "POST /github", "POST /stripe", "POST /discord",
                    "POST /notion", "POST /vercel", "POST /trading",
                    "POST /astra", "POST /custom/*",
                ],
            })
        elif path == "/":
            self._respond(200, {
                "service": "ASTRA Webhooks",
                "port": WEBHOOK_PORT,
                "docs": "POST JSON to /github, /stripe, /discord, /notion, /vercel, /trading, /astra, or /custom/<name>",
            })
        else:
            self._respond(404, {"error": "Not found", "hint": "Use GET /health"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        try:
            payload = json.loads(body) if body else {}
        except Exception:
            payload = {"raw": body.decode(errors="replace")}

        path = urlparse(self.path).path
        event = self._route(path, payload, dict(self.headers))
        self._respond(200, {"received": True, "event": event, "path": path})

        # Emit to brain
        if getattr(self.server, "event_cb", None):
            self.server.event_cb({
                "type": "webhook_in",
                "path": path,
                "payload": payload,
                "event": event,
            })

    def _route(self, path: str, payload: dict, headers: dict) -> str:
        """Identify webhook source and return event name."""
        if path == "/github":
            event = headers.get("X-GitHub-Event", "unknown")
            return f"github.{event}"
        elif path == "/stripe":
            return f"stripe.{payload.get('type', 'event')}"
        elif path == "/discord":
            return "discord.message"
        elif path == "/notion":
            return "notion.update"
        elif path == "/vercel":
            return f"vercel.{payload.get('type', 'deploy')}"
        elif path == "/trading":
            return "trading.alert"
        elif path == "/astra":
            return "astra.command"
        elif path.startswith("/custom"):
            return f"custom{path.replace('/', '.')}"
        else:
            return f"custom{path.replace('/', '.')}"

    def _respond(self, code: int, data: dict):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)


class ASTRAWebhookServer:
    def __init__(self, event_cb=None, port=None):
        self.event_cb = event_cb
        self.port = int(port or WEBHOOK_PORT)
        self.server = None
        self.outgoing_queue = []

    def start(self):
        global WEBHOOK_PORT
        WEBHOOK_PORT = self.port
        self.server = HTTPServer(("0.0.0.0", self.port), WebhookHandler)
        self.server.event_cb = self.event_cb
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        if self.event_cb:
            self.event_cb({
                "type": "webhook_server_ready",
                "msg": f"Webhook engine online at http://localhost:{self.port}",
                "port": self.port,
            })

    def stop(self):
        if self.server:
            self.server.shutdown()

    def trigger(self, url: str, payload: dict, secret: str = None) -> bool:
        """Send an outgoing webhook."""
        try:
            body = json.dumps(payload).encode()
            headers = {"Content-Type": "application/json"}
            if secret:
                sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
                headers["X-ASTRA-Signature"] = f"sha256={sig}"
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status < 300
        except Exception as e:
            if self.event_cb:
                self.event_cb({"type": "warn", "msg": f"Outgoing webhook failed: {e}"})
            return False


# ── Predefined outgoing triggers ─────────────────────────────────────────────
TRIGGERS = {
    "task_complete": lambda proj, task: {
        "event": "task.complete",
        "project": proj,
        "task": task,
        "timestamp": time.time()
    },
    "focus_start": lambda mins: {
        "event": "focus.start",
        "duration_minutes": mins,
        "timestamp": time.time()
    },
    "deploy_request": lambda repo, env: {
        "event": "deploy.request",
        "repository": repo,
        "environment": env,
        "timestamp": time.time()
    },
    "trading_alert": lambda symbol, signal, price: {
        "event": "trading.alert",
        "symbol": symbol,
        "signal": signal,
        "price": price,
        "timestamp": time.time()
    },
}
