"""
ASTRA agent tools — sandboxed filesystem + allowlisted shell + memory hooks.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

HOME = Path.home()
# Safe work roots (Windows + portable)
ALLOWED_ROOTS = [
    HOME / "OneDrive" / "Desktop",
    HOME / "Desktop",
    HOME / "Documents",
    HOME / "Downloads",
    Path(__file__).resolve().parents[2],  # astra project root
]

SHELL_ALLOW = [
    r"^dir(\s|$)",
    r"^ls(\s|$)",
    r"^pwd$",
    r"^echo\s+",
    r"^git\s+(status|log|branch|diff|remote)(\s|$)",
    r"^npm\s+(--version|version|list|outdated)(\s|$)",
    r"^node\s+--version$",
    r"^python(\s+--version)?$",
    r"^py\s+-3\s+--version$",
    r"^whoami$",
    r"^hostname$",
    r"^date$",
]


def _resolve_safe(path_str: str) -> Path:
    raw = Path(path_str).expanduser()
    try:
        p = raw.resolve()
    except Exception:
        p = (Path.cwd() / raw).resolve()
    for root in ALLOWED_ROOTS:
        try:
            r = root.resolve()
            if p == r or r in p.parents or p in r.parents or str(p).startswith(str(r)):
                # must be under an allowed root
                if str(p).lower().startswith(str(r).lower()):
                    return p
        except Exception:
            continue
    raise PermissionError(f"Path not in allowlist: {path_str}")


def tool_list_dir(path: str = ".", limit: int = 80) -> dict:
    p = _resolve_safe(path or str(HOME / "Desktop"))
    if not p.exists():
        return {"ok": False, "error": f"Not found: {p}"}
    if not p.is_dir():
        return {"ok": False, "error": f"Not a directory: {p}"}
    entries = []
    for i, child in enumerate(sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))):
        if i >= limit:
            entries.append({"name": "…", "type": "truncated"})
            break
        entries.append({
            "name": child.name,
            "type": "dir" if child.is_dir() else "file",
            "size": child.stat().st_size if child.is_file() else None,
        })
    return {"ok": True, "path": str(p), "entries": entries}


def tool_read_file(path: str, max_bytes: int = 40000) -> dict:
    p = _resolve_safe(path)
    if not p.is_file():
        return {"ok": False, "error": f"Not a file: {p}"}
    data = p.read_bytes()[:max_bytes]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("utf-8", errors="replace")
    return {
        "ok": True,
        "path": str(p),
        "bytes": len(data),
        "truncated": p.stat().st_size > max_bytes,
        "content": text,
    }


def tool_write_file(path: str, content: str, mode: str = "write") -> dict:
    p = _resolve_safe(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if mode == "append" and p.exists():
        with open(p, "a", encoding="utf-8") as f:
            f.write(content)
    else:
        p.write_text(content, encoding="utf-8")
    return {"ok": True, "path": str(p), "bytes": len(content.encode("utf-8"))}


def tool_run_shell(cmd: str, timeout: int = 20) -> dict:
    cmd = (cmd or "").strip()
    if not cmd:
        return {"ok": False, "error": "Empty command"}
    if not any(re.search(pat, cmd, re.I) for pat in SHELL_ALLOW):
        return {
            "ok": False,
            "error": "Command not allowlisted. Allowed: dir/ls, git status/log/branch/diff, npm version, node/python --version, echo, whoami, date",
            "cmd": cmd,
        }
    try:
        r = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(HOME),
        )
        out = (r.stdout or "")[-8000:]
        err = (r.stderr or "")[-2000:]
        return {"ok": r.returncode == 0, "code": r.returncode, "stdout": out, "stderr": err, "cmd": cmd}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Command timed out", "cmd": cmd}
    except Exception as e:
        return {"ok": False, "error": str(e), "cmd": cmd}


def tool_system_info() -> dict:
    import platform
    return {
        "ok": True,
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cwd": os.getcwd(),
        "home": str(HOME),
        "time": datetime.now().isoformat(timespec="seconds"),
    }


TOOL_DEFS = [
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List files in an allowed directory (Desktop, Documents, Downloads, ASTRA project).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path"},
                    "limit": {"type": "integer", "description": "Max entries", "default": 80},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a text file from an allowed path.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write or append a text file under allowed roots.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "mode": {"type": "string", "enum": ["write", "append"], "default": "write"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": "Run an allowlisted shell command (git status, dir, versions, echo).",
            "parameters": {
                "type": "object",
                "properties": {"cmd": {"type": "string"}},
                "required": ["cmd"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "system_info",
            "description": "Get OS, Python version, home path, time.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


def run_tool(name: str, args: dict) -> dict:
    args = args or {}
    if name == "list_dir":
        return tool_list_dir(args.get("path", str(HOME / "Desktop")), int(args.get("limit") or 80))
    if name == "read_file":
        return tool_read_file(args.get("path", ""))
    if name == "write_file":
        return tool_write_file(args.get("path", ""), args.get("content", ""), args.get("mode", "write"))
    if name == "run_shell":
        return tool_run_shell(args.get("cmd", ""))
    if name == "system_info":
        return tool_system_info()
    return {"ok": False, "error": f"Unknown tool: {name}"}


# Simple intent-based tool use when cloud tool-calling unavailable
def demo_agent(prompt: str, emit=None) -> str:
    p = prompt.lower()
    steps = []
    if "system" in p or "who am i" in p or "platform" in p:
        r = tool_system_info()
        steps.append(("system_info", r))
    if "list" in p or "files" in p or "desktop" in p or "dir" in p:
        r = tool_list_dir(str(HOME / "OneDrive" / "Desktop" if (HOME / "OneDrive" / "Desktop").exists() else HOME / "Desktop"))
        steps.append(("list_dir", r))
    if "git status" in p or ("git" in p and "status" in p):
        r = tool_run_shell("git status")
        steps.append(("run_shell", r))
    if not steps:
        # default: system info + desktop list
        steps.append(("system_info", tool_system_info()))
        desk = HOME / "OneDrive" / "Desktop"
        if not desk.exists():
            desk = HOME / "Desktop"
        steps.append(("list_dir", tool_list_dir(str(desk), 20)))

    lines = ["**Agent run (local tools)**\n"]
    for name, result in steps:
        if emit:
            emit({"type": "tool_call", "name": name, "args": {}, "result_ok": result.get("ok")})
        lines.append(f"### `{name}`")
        lines.append("```json")
        lines.append(json.dumps(result, indent=2)[:2500])
        lines.append("```\n")
    lines.append("_Cloud tool-calling unavailable or offline — used allowlisted local tools._")
    return "\n".join(lines)
