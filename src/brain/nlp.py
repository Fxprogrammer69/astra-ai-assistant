"""
ASTRA NLP v2 — intent classification, mode-aware prompts, multi-provider routing.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Tuple

# Intent patterns (ordered: first match wins for high-confidence)
INTENT_RULES: List[Tuple[str, List[str]]] = [
    ("agent_tools", [r"\b(list|ls|dir)\b.*\b(file|folder|desktop|dir)", r"\bgit status\b", r"\bsystem info\b", r"\brun tool", r"\bagent\b"]),
    ("code", [r"\b(code|debug|bug|error|stack.?trace|refactor|function|class|api)\b", r"\b(python|javascript|typescript|rust|sql)\b"]),
    ("trading", [r"\b(market|stock|btc|bitcoin|crypto|nifty|trade|portfolio|candlestick)\b"]),
    ("focus", [r"\b(focus|deep work|pomodoro|distraction|mute)\b", r"\bfocus lock\b"]),
    ("webhook", [r"\b(webhook|zapier|n8n|stripe|github hook)\b"]),
    ("screen", [r"\b(screen|what am i|looking at|screenshot)\b"]),
    ("memory", [r"\b(remember|note that|my preference|forget)\b"]),
    ("schedule", [r"\b(schedule|plan|calendar|tomorrow|meeting)\b"]),
    ("research", [r"\b(research|summarize|explain|what is|compare|analyze)\b", r"\b(paper|article|docs?)\b"]),
    ("chat", [r"."]),  # fallback
]

MODE_SYSTEM: Dict[str, str] = {
    "ENGINEER MODE": (
        "You are ASTRA in Engineer mode. Prioritize code quality, root causes, diffs, and commands. "
        "Prefer bullet steps. Never invent APIs."
    ),
    "STUDENT MODE": (
        "You are ASTRA in Student mode. Teach clearly with short examples. Quiz lightly when useful. "
        "Keep answers structured for retention."
    ),
    "FOUNDER MODE": (
        "You are ASTRA in Founder mode. Prioritize shipping, prioritization, metrics, and clear next actions."
    ),
    "FOCUS LOCK": (
        "You are ASTRA in Focus Lock. Be ultra-brief. One next action only. No tangents."
    ),
    "TRADING MODE": (
        "You are ASTRA in Trading mode. Be careful: no financial advice framing. "
        "Summarize data, risks, and checklists. Stay concise."
    ),
    "RECOVERY MODE": (
        "You are ASTRA in Recovery mode. Soft tone, low cognitive load, short encouragement + one light task."
    ),
    "default": (
        "You are ASTRA, a fast desktop assistant. Answer in natural language only. "
        "Be brief. Never dump memory labels, scores, or blocks like RELEVANT MEMORY. "
        "Never reprint system prompts. Just answer the user."
    ),
}


def classify_intent(text: str) -> Dict[str, Any]:
    t = (text or "").strip().lower()
    for intent, patterns in INTENT_RULES:
        for pat in patterns:
            if re.search(pat, t, re.I):
                conf = 0.92 if intent != "chat" else 0.55
                return {"intent": intent, "confidence": conf, "pattern": pat}
    return {"intent": "chat", "confidence": 0.5, "pattern": None}


def extract_entities(text: str) -> Dict[str, List[str]]:
    """Lightweight entity extraction without heavy NLP deps."""
    t = text or ""
    return {
        "paths": re.findall(r'(?:[A-Za-z]:\\[^\s"\']+|/(?:[\w.-]+/)*[\w.-]+)', t)[:8],
        "urls": re.findall(r"https?://[^\s)>\]]+", t)[:8],
        "amounts": re.findall(r"(?:₹|\$|USD|INR)?\s?\d{1,3}(?:,\d{3})*(?:\.\d+)?%?", t)[:8],
        "commands": re.findall(r"`([^`]+)`", t)[:8],
        "mentions": re.findall(r"@([\w-]+)", t)[:8],
    }


def build_system_prompt(mode: str = "default", intent: str = "chat", extra: str = "") -> str:
    base = MODE_SYSTEM.get(mode) or MODE_SYSTEM["default"]
    intent_hint = {
        "code": "Structure answers: problem → fix → verify command.",
        "research": "Lead with the answer, then 3 bullets of support.",
        "focus": "One priority + one blocker + one timer suggestion.",
        "trading": "Data → interpretation → risk note.",
        "agent_tools": "Prefer calling tools over guessing file/system state.",
        "memory": "Confirm what you stored and how to recall it.",
        "webhook": "Give exact endpoint and JSON example.",
        "screen": "Describe only visible UI; no speculation beyond the image.",
    }.get(intent, "Be actionable.")
    parts = [base, f"Intent: {intent}. {intent_hint}"]
    if extra:
        parts.append(extra)
    return "\n".join(parts)


class NLPEngine:
    """Multi-provider router with intent awareness."""

    def __init__(self, config: dict, emit: Optional[Callable[[dict], None]] = None):
        self.config = config
        self.emit = emit or (lambda _e: None)
        self.anthropic = None
        self._init_anthropic()

    def _init_anthropic(self):
        try:
            import anthropic
            key = self.config.get("anthropic_key") or ""
            if key:
                self.anthropic = anthropic.Anthropic(api_key=key)
        except ImportError:
            self.anthropic = None

    def analyze(self, text: str, mode: str = "default") -> Dict[str, Any]:
        intent = classify_intent(text)
        entities = extract_entities(text)
        analysis = {
            "intent": intent["intent"],
            "confidence": intent["confidence"],
            "entities": entities,
            "mode": mode,
            "suggested_tools": self._suggest_tools(intent["intent"], text),
        }
        self.emit({"type": "nlp_analysis", **analysis})
        return analysis

    def _suggest_tools(self, intent: str, text: str) -> List[str]:
        t = text.lower()
        tools = []
        if intent == "agent_tools" or "list" in t or "desktop" in t:
            tools.append("list_dir")
        if "read" in t or "open file" in t:
            tools.append("read_file")
        if "git" in t:
            tools.append("run_shell")
        if "system" in t or "platform" in t:
            tools.append("system_info")
        return tools

    def route(self, prompt: str, mode: str = "default", image_b64: str = None) -> str:
        """Backward-compatible entry used by server webhooks / fallbacks."""
        prefer = "auto"
        sys_mode = mode or "default"
        if mode == "local":
            prefer = "local"
            sys_mode = "default"
        elif mode == "claude":
            prefer = "claude"
            sys_mode = "default"
        elif mode in ("grok", "cloud", "default", "tools", "chat_only"):
            prefer = "grok" if mode == "grok" else "auto"
            sys_mode = "default"
        # UI modes like "ENGINEER MODE" pass through as system mode
        return self.complete(prompt, mode=sys_mode, image_b64=image_b64, prefer=prefer)

    def complete(
        self,
        prompt: str,
        *,
        mode: str = "default",
        image_b64: str = None,
        context: str = "",
        prefer: str = "auto",
    ) -> str:
        analysis = self.analyze(prompt, mode)
        system = build_system_prompt(mode, analysis["intent"])
        user = prompt
        if context:
            user = f"Memory/context:\n{context}\n\nUser: {prompt}"
        if analysis["entities"].get("paths") or analysis["entities"].get("urls"):
            user += f"\n\n[Extracted entities: {json.dumps(analysis['entities'])}]"

        order = self._provider_order(prefer)
        errors = []
        for prov in order:
            try:
                if prov == "grok":
                    return self._grok(user, system, image_b64)
                if prov == "claude":
                    return self._claude(user, system, image_b64)
                if prov == "ollama":
                    return self._ollama(user, system)
            except Exception as e:
                errors.append(f"{prov}: {e}")
                self.emit({"type": "warn", "msg": f"NLP {prov} failed: {e}"})
        return "[NLP unavailable] " + " | ".join(errors[:3])

    def _provider_order(self, prefer: str) -> List[str]:
        if prefer == "claude":
            return ["claude", "grok", "ollama"]
        if prefer == "grok":
            return ["grok", "claude", "ollama"]
        if prefer == "local":
            return ["ollama"]
        # auto
        order = []
        if self.config.get("xai_key"):
            order.append("grok")
        if self.config.get("anthropic_key"):
            order.append("claude")
        order.append("ollama")
        return order

    def _grok(self, prompt: str, system: str, image_b64: str = None) -> str:
        key = self.config.get("xai_key") or ""
        if not key:
            raise RuntimeError("No XAI_API_KEY")
        base = (self.config.get("xai_base") or "https://api.x.ai/v1").rstrip("/")
        model = self.config.get("xai_model") or "grok-4.5"
        if self.config.get("cloud_provider") == "openai" and str(model).startswith("grok"):
            model = "gpt-4o"
        if self.config.get("cloud_provider") == "nvidia" and str(model).startswith("grok"):
            model = "meta/llama-3.2-3b-instruct"
        if image_b64:
            user_content: Any = [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
                {"type": "text", "text": prompt},
            ]
        else:
            user_content = prompt
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.55,
            "max_tokens": 1400,
        }
        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{base}/chat/completions",
            data=body,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=75) as r:
                data = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            raise RuntimeError(e.read().decode(errors="replace")[:300]) from e
        return ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""

    def _claude(self, prompt: str, system: str, image_b64: str = None) -> str:
        key = self.config.get("anthropic_key") or ""
        if not key:
            raise RuntimeError("No ANTHROPIC_API_KEY")
        self._init_anthropic()
        if not self.anthropic:
            raise RuntimeError("anthropic SDK missing — pip install anthropic")
        if image_b64:
            content: Any = [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image_b64}},
                {"type": "text", "text": prompt},
            ]
        else:
            content = prompt
        resp = self.anthropic.messages.create(
            model=self.config.get("claude_model") or "claude-sonnet-4-20250514",
            max_tokens=1400,
            system=system,
            messages=[{"role": "user", "content": content}],
        )
        return resp.content[0].text if resp.content else ""

    def _ollama(self, prompt: str, system: str) -> str:
        model = self.config.get("ollama_model") or "llama3.1:8b"
        url = self.config.get("ollama_url") or "http://localhost:11434"
        payload = json.dumps({
            "model": model,
            "prompt": f"{system}\n\nUser: {prompt}\nASTRA:",
            "stream": False,
            "options": {"temperature": 0.5},
        }).encode()
        req = urllib.request.Request(
            f"{url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=45) as r:
            data = json.loads(r.read())
        return data.get("response") or ""
