"""Predefined ASTRA missions (one-click workflows)."""
from __future__ import annotations

from typing import Callable, List, Dict, Any

from tools import tool_list_dir, tool_run_shell, tool_system_info
from pathlib import Path


def _desk() -> str:
    home = Path.home()
    od = home / "OneDrive" / "Desktop"
    return str(od if od.exists() else home / "Desktop")


MISSIONS: List[Dict[str, Any]] = [
    {
        "id": "system_scan",
        "name": "System scan",
        "desc": "Platform info + Desktop file listing",
        "icon": "radar-2",
    },
    {
        "id": "git_status",
        "name": "Git status",
        "desc": "Run allowlisted git status in home",
        "icon": "git-branch",
    },
    {
        "id": "desktop_inventory",
        "name": "Desktop inventory",
        "desc": "List Desktop folders and files",
        "icon": "folder",
    },
    {
        "id": "focus_prep",
        "name": "Focus prep",
        "desc": "Checklist for a deep-work block",
        "icon": "target",
    },
    {
        "id": "webhook_health",
        "name": "Webhook health",
        "desc": "Remind endpoints + health URL",
        "icon": "webhook",
    },
]


def run_mission(mission_id: str, emit: Callable[[dict], None] | None = None) -> str:
    def _e(ev):
        if emit:
            emit(ev)

    if mission_id == "system_scan":
        _e({"type": "tool_call", "name": "system_info", "status": "running"})
        info = tool_system_info()
        _e({"type": "tool_result", "name": "system_info", "ok": True})
        _e({"type": "tool_call", "name": "list_dir", "status": "running"})
        listing = tool_list_dir(_desk(), 25)
        _e({"type": "tool_result", "name": "list_dir", "ok": listing.get("ok")})
        return (
            "## Mission: System scan\n\n"
            f"**Platform:** `{info.get('platform')}`\n"
            f"**Python:** `{info.get('python')}`\n"
            f"**Time:** `{info.get('time')}`\n\n"
            f"**Desktop** (`{listing.get('path')}`):\n"
            + "\n".join(
                f"- {'📁' if e.get('type')=='dir' else '📄'} {e.get('name')}"
                for e in (listing.get('entries') or [])[:25]
            )
        )

    if mission_id == "git_status":
        _e({"type": "tool_call", "name": "run_shell", "args": {"cmd": "git status"}, "status": "running"})
        r = tool_run_shell("git status")
        _e({"type": "tool_result", "name": "run_shell", "ok": r.get("ok")})
        return f"## Mission: Git status\n\n```\n{r.get('stdout') or r.get('stderr') or r.get('error')}\n```"

    if mission_id == "desktop_inventory":
        r = tool_list_dir(_desk(), 60)
        return (
            f"## Mission: Desktop inventory\n\n`{r.get('path')}`\n\n"
            + "\n".join(f"- {e.get('type')}: **{e.get('name')}**" for e in (r.get("entries") or []))
        )

    if mission_id == "focus_prep":
        return (
            "## Mission: Focus prep\n\n"
            "1. Mute notifications · close chat apps\n"
            "2. Start **Focus Lock** mode (Ctrl+Shift+F)\n"
            "3. Set timer 25–50m\n"
            "4. Write one outcome sentence\n"
            "5. Start work — ASTRA is on standby\n"
        )

    if mission_id == "webhook_health":
        return (
            "## Mission: Webhook health\n\n"
            "- Engine: `http://localhost:9003/health`\n"
            "- POST `/github` `/stripe` `/astra` `/custom/*`\n"
            "- UI: Webhooks view → **Send test**\n"
            "- Mobile WS: `ws://localhost:9001`\n"
        )

    return f"Unknown mission: {mission_id}"
