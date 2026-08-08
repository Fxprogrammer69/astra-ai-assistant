"""
Minimal MCP (Model Context Protocol) client for ASTRA.
Connects to external MCP servers over stdio JSON-RPC and exposes tools.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent.parent
MCP_CONFIG = ROOT / "models" / "mcp.json"


DEFAULT_CONFIG = {
    "servers": [
        # Example (enable by setting "enabled": true):
        # {
        #   "name": "filesystem",
        #   "enabled": false,
        #   "command": "npx",
        #   "args": ["-y", "@modelcontextprotocol/server-filesystem", str(Path.home())],
        #   "env": {}
        # }
    ]
}


class MCPServerProc:
    def __init__(self, name: str, command: str, args: List[str], env: Optional[dict] = None, emit=None):
        self.name = name
        self.command = command
        self.args = args or []
        self.env = env or {}
        self.emit = emit or (lambda _e: None)
        self.proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._pending: Dict[str, Any] = {}
        self._tools: List[dict] = []
        self._reader = None
        self._alive = False
        self._msg_id = 0

    def start(self) -> bool:
        if self.proc and self.proc.poll() is None:
            return True
        env = {**os.environ, **{k: str(v) for k, v in self.env.items()}}
        try:
            self.proc = subprocess.Popen(
                [self.command, *self.args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                text=True,
                bufsize=1,
                cwd=str(ROOT),
            )
        except Exception as e:
            self.emit({"type": "mcp_error", "server": self.name, "msg": f"spawn failed: {e}"})
            return False
        self._alive = True
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        # Initialize handshake
        try:
            self._request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "astra", "version": "1.0.0"},
            }, timeout=12)
            self._notify("notifications/initialized", {})
            tools = self._request("tools/list", {}, timeout=12) or {}
            self._tools = tools.get("tools") or []
            self.emit({
                "type": "mcp_ready",
                "server": self.name,
                "tools": [t.get("name") for t in self._tools],
            })
            return True
        except Exception as e:
            self.emit({"type": "mcp_error", "server": self.name, "msg": f"init failed: {e}"})
            self.stop()
            return False

    def stop(self):
        self._alive = False
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except Exception:
                pass
        self.proc = None
        self._tools = []

    def _next_id(self) -> str:
        self._msg_id += 1
        return str(self._msg_id)

    def _read_loop(self):
        assert self.proc and self.proc.stdout
        for line in self.proc.stdout:
            if not self._alive:
                break
            line = (line or "").strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except Exception:
                continue
            mid = msg.get("id")
            if mid is not None and str(mid) in self._pending:
                ev = self._pending[str(mid)]
                ev["result"] = msg.get("result")
                ev["error"] = msg.get("error")
                ev["event"].set()

    def _notify(self, method: str, params: dict):
        if not self.proc or not self.proc.stdin:
            return
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        with self._lock:
            self.proc.stdin.write(json.dumps(payload) + "\n")
            self.proc.stdin.flush()

    def _request(self, method: str, params: dict, timeout: float = 20) -> Any:
        if not self.proc or not self.proc.stdin:
            raise RuntimeError("MCP server not running")
        mid = self._next_id()
        event = threading.Event()
        self._pending[mid] = {"event": event, "result": None, "error": None}
        payload = {"jsonrpc": "2.0", "id": mid, "method": method, "params": params}
        with self._lock:
            self.proc.stdin.write(json.dumps(payload) + "\n")
            self.proc.stdin.flush()
        if not event.wait(timeout):
            self._pending.pop(mid, None)
            raise TimeoutError(f"MCP {self.name} timeout on {method}")
        data = self._pending.pop(mid, {})
        if data.get("error"):
            raise RuntimeError(str(data["error"]))
        return data.get("result")

    def list_tools(self) -> List[dict]:
        return list(self._tools)

    def call_tool(self, name: str, arguments: Optional[dict] = None) -> Any:
        return self._request("tools/call", {
            "name": name,
            "arguments": arguments or {},
        }, timeout=60)


class MCPManager:
    def __init__(self, emit: Optional[Callable[[dict], None]] = None):
        self.emit = emit or (lambda _e: None)
        self.servers: Dict[str, MCPServerProc] = {}
        self.config = self._load()

    def _load(self) -> dict:
        MCP_CONFIG.parent.mkdir(parents=True, exist_ok=True)
        if not MCP_CONFIG.exists():
            MCP_CONFIG.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")
            return dict(DEFAULT_CONFIG)
        try:
            return json.loads(MCP_CONFIG.read_text(encoding="utf-8"))
        except Exception:
            return dict(DEFAULT_CONFIG)

    def reload(self):
        self.config = self._load()

    def start_enabled(self):
        for srv in self.config.get("servers") or []:
            if not srv.get("enabled"):
                continue
            name = srv.get("name") or f"srv_{uuid.uuid4().hex[:6]}"
            if name in self.servers and self.servers[name].proc:
                continue
            proc = MCPServerProc(
                name=name,
                command=srv.get("command") or "npx",
                args=list(srv.get("args") or []),
                env=dict(srv.get("env") or {}),
                emit=self.emit,
            )
            if proc.start():
                self.servers[name] = proc

    def stop_all(self):
        for s in list(self.servers.values()):
            s.stop()
        self.servers.clear()

    def status(self) -> dict:
        out = []
        for name, s in self.servers.items():
            out.append({
                "name": name,
                "alive": bool(s.proc and s.proc.poll() is None),
                "tools": [t.get("name") for t in s.list_tools()],
            })
        configured = [
            {"name": s.get("name"), "enabled": bool(s.get("enabled")), "command": s.get("command")}
            for s in (self.config.get("servers") or [])
        ]
        return {"running": out, "configured": configured, "config_path": str(MCP_CONFIG)}

    def all_tools(self) -> List[dict]:
        tools = []
        for name, s in self.servers.items():
            for t in s.list_tools():
                tools.append({
                    "server": name,
                    "name": t.get("name"),
                    "description": t.get("description") or "",
                    "inputSchema": t.get("inputSchema") or {},
                    "qualified": f"mcp__{name}__{t.get('name')}",
                })
        return tools

    def call(self, qualified_or_name: str, arguments: Optional[dict] = None, server: Optional[str] = None) -> Any:
        # mcp__server__tool or bare name
        if qualified_or_name.startswith("mcp__"):
            parts = qualified_or_name.split("__", 2)
            if len(parts) == 3:
                server, tool = parts[1], parts[2]
                if server in self.servers:
                    return self.servers[server].call_tool(tool, arguments)
        if server and server in self.servers:
            return self.servers[server].call_tool(qualified_or_name, arguments)
        # search
        for name, s in self.servers.items():
            for t in s.list_tools():
                if t.get("name") == qualified_or_name:
                    return s.call_tool(qualified_or_name, arguments)
        raise KeyError(f"MCP tool not found: {qualified_or_name}")
