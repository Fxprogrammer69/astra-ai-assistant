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

    def do_GET(self):
        if self.path == "/health":
            self._respond(200, {"status": "ASTRA webhook engine online", "port": WEBHOOK_PORT})
        else:
            self._respond(404, {"error": "Not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        try:
            payload = json.loads(body)
        except Exception:
            payload = {"raw": body.decode(errors="replace")}

        path = urlparse(self.path).path
        event = self._route(path, payload, dict(self.headers))
        self._respond(200, {"received": True, "event": event})

        # Emit to brain
        if self.server.event_cb:
            self.server.event_cb({"type": "webhook_in", "path": path, "payload": payload, "event": event})

    def _route(self, path: str, payload: dict, headers: dict) -> str:
        """Identify webhook source and return event name."""
        if path == "/github":
            event = headers.get("X-GitHub-Event", "unknown")
            return f"github.{event}"
        elif path == "/stripe":
            return f"stripe.{payload.get('type','event')}"
        elif path == "/discord":
            return "discord.message"
        elif path == "/notion":
            return "notion.update"
        elif path == "/vercel":
            return f"vercel.{payload.get('type','deploy')}"
        elif path == "/trading":
            return f"trading.alert"
        else:
            return f"custom{path.replace('/','.')}"

    def _respond(self, code: int, data: dict):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)


class ASTRAWebhookServer:
    def __init__(self, event_cb=None):
        self.event_cb = event_cb
        self.server = None
        self.outgoing_queue = []

    def start(self):
        self.server = HTTPServer(("0.0.0.0", WEBHOOK_PORT), WebhookHandler)
        self.server.event_cb = self.event_cb
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        if self.event_cb:
            self.event_cb({"type": "webhook_server_ready",
                           "msg": f"Webhook engine online at http://localhost:{WEBHOOK_PORT}"})

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
