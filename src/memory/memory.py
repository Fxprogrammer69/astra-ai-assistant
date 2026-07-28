#!/usr/bin/env python3
"""
ASTRA Memory Layer
Persistent JSON-based memory with categories:
goals, projects, tasks, preferences, context, routines
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path

MEMORY_PATH = Path(__file__).parent.parent.parent / "models" / "memory.json"

DEFAULT_MEMORY = {
    "version": "1.0",
    "created": datetime.now().isoformat(),
    "goals": [],
    "projects": [],
    "tasks": [],
    "routines": [],
    "preferences": {
        "mode": "engineer",
        "theme": "dark",
        "focus_duration": 25,
        "ollama_model": "llama3.1:8b",
        "whisper_model": "tiny"
    },
    "context": [],
    "notes": [],
    "trading_journal": []
}

class Memory:
    def __init__(self):
        MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.data = self._load()

    def _load(self) -> dict:
        try:
            with open(MEMORY_PATH) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self._save(DEFAULT_MEMORY)
            return DEFAULT_MEMORY.copy()

    def _save(self, data=None):
        with open(MEMORY_PATH, "w") as f:
            json.dump(data or self.data, f, indent=2)

    # ── Context (conversation history) ────────────────────────────────────────
    def add_context(self, role: str, text: str):
        self.data["context"].append({
            "role": role, "text": text,
            "ts": datetime.now().isoformat()
        })
        if len(self.data["context"]) > 200:
            self.data["context"] = self.data["context"][-200:]
        self._save()

    def get_context(self, n: int = 10) -> str:
        recent = self.data["context"][-n:]
        return "\n".join(f"{c['role'].upper()}: {c['text']}" for c in recent)

    # ── Goals ─────────────────────────────────────────────────────────────────
    def add_goal(self, title: str, category: str = "general", deadline: str = None):
        self.data["goals"].append({
            "id": int(time.time()), "title": title,
            "category": category, "deadline": deadline,
            "done": False, "created": datetime.now().isoformat()
        })
        self._save()

    # ── Projects ──────────────────────────────────────────────────────────────
    def add_project(self, name: str, description: str = "", stack: list = None):
        self.data["projects"].append({
            "id": int(time.time()), "name": name,
            "description": description, "stack": stack or [],
            "status": "active", "created": datetime.now().isoformat()
        })
        self._save()

    # ── Tasks ─────────────────────────────────────────────────────────────────
    def add_task(self, title: str, tag: str = "GENERAL", project: str = None):
        self.data["tasks"].append({
            "id": int(time.time()), "title": title,
            "tag": tag, "project": project,
            "done": False, "created": datetime.now().isoformat()
        })
        self._save()

    def complete_task(self, task_id: int):
        for t in self.data["tasks"]:
            if t["id"] == task_id:
                t["done"] = True
                t["completed_at"] = datetime.now().isoformat()
        self._save()

    # ── Notes ─────────────────────────────────────────────────────────────────
    def add_note(self, text: str, tags: list = None):
        self.data["notes"].append({
            "id": int(time.time()), "text": text,
            "tags": tags or [], "ts": datetime.now().isoformat()
        })
        self._save()

    # ── Trading Journal ───────────────────────────────────────────────────────
    def add_trade(self, symbol: str, direction: str, entry: float,
                  exit_price: float = None, notes: str = ""):
        self.data["trading_journal"].append({
            "id": int(time.time()), "symbol": symbol,
            "direction": direction, "entry": entry,
            "exit": exit_price, "notes": notes,
            "ts": datetime.now().isoformat()
        })
        self._save()

    # ── Preferences ───────────────────────────────────────────────────────────
    def set_pref(self, key: str, value):
        self.data["preferences"][key] = value
        self._save()

    def get_pref(self, key: str, default=None):
        return self.data["preferences"].get(key, default)

    # ── Summary ───────────────────────────────────────────────────────────────
    def summary(self) -> str:
        g = len(self.data["goals"])
        p = len(self.data["projects"])
        t_total = len(self.data["tasks"])
        t_done  = sum(1 for t in self.data["tasks"] if t["done"])
        n = len(self.data["notes"])
        return (f"Goals: {g} | Projects: {p} | "
                f"Tasks: {t_done}/{t_total} done | Notes: {n}")

    def export(self) -> dict:
        return self.data.copy()
