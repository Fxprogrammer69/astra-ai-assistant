#!/usr/bin/env python3
"""
ASTRA Brain Server
Grok (xAI) + Ollama routing, Whisper STT, MediaPipe CV, Webhooks
Communicates with Electron via stdin/stdout JSON
"""

import sys
import json
import threading
import time
import base64
import os
from datetime import datetime
from pathlib import Path

# Ensure sibling packages importable
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Load .env from project root if present
def _load_dotenv():
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if not env_path.exists():
        return
    try:
        # utf-8-sig strips BOM so keys like NVIDIA_NIM_API_KEY still load
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

# ── Lazy imports ──────────────────────────────────────────────────────────────
def try_import(name):
    try:
        return __import__(name)
    except ImportError:
        print(json.dumps({"type": "warn", "msg": f"Module '{name}' not installed. Run setup.py."}), flush=True)
        return None

# ── Config ────────────────────────────────────────────────────────────────────
def _detect_cloud():
    """Resolve cloud LLM endpoint from env keys.
    NVIDIA NIM (nvapi-… / NVIDIA_NIM_API_KEY) → integrate.api.nvidia.com
    True xAI keys (xai-…) → Grok on api.x.ai
    OpenAI-style keys (sk-…) → OpenAI-compatible chat
    """
    nvidia = (
        os.environ.get("NVIDIA_NIM_API_KEY")
        or os.environ.get("NVIDIA_API_KEY")
        or ""
    ).strip()
    raw = (
        nvidia
        or os.environ.get("XAI_API_KEY")
        or os.environ.get("GROK_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or ""
    ).strip()
    base = (
        os.environ.get("NVIDIA_BASE_URL")
        or os.environ.get("XAI_BASE_URL")
        or ""
    ).rstrip("/")
    model = (
        os.environ.get("NVIDIA_MODEL")
        or os.environ.get("XAI_MODEL")
        or os.environ.get("OPENAI_MODEL")
        or ""
    )

    if not raw:
        return {"key": "", "base": "https://api.x.ai/v1", "model": "grok-4.5", "provider": "none"}

    # NVIDIA NIM (OpenAI-compatible)
    if raw.startswith("nvapi-") or bool(nvidia) or "nvidia.com" in base:
        return {
            "key": raw,
            "base": base or "https://integrate.api.nvidia.com/v1",
            "model": model or "meta/llama-3.2-3b-instruct",
            "provider": "nvidia",
        }

    if raw.startswith("xai-") or "x.ai" in base:
        return {
            "key": raw,
            "base": base or "https://api.x.ai/v1",
            "model": model or "grok-4.5",
            "provider": "grok",
        }

    # OpenAI / project keys (sk- / sk-proj-)
    if raw.startswith("sk-"):
        return {
            "key": raw,
            "base": base or "https://api.openai.com/v1",
            "model": model or "gpt-4o",
            "provider": "openai",
        }

    # Unknown format — try xAI first (user may have custom key)
    return {
        "key": raw,
        "base": base or "https://api.x.ai/v1",
        "model": model or "grok-4.5",
        "provider": "grok",
    }


_cloud = _detect_cloud()

CONFIG = {
    "xai_key": _cloud["key"],
    "xai_base": _cloud["base"],
    "xai_model": _cloud["model"],
    "cloud_provider": _cloud["provider"],
    "anthropic_key": os.environ.get("ANTHROPIC_API_KEY", ""),
    "claude_model": os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-20250514"),
    "ollama_url": os.environ.get("OLLAMA_URL", "http://localhost:11434"),
    "ollama_model": os.environ.get("OLLAMA_MODEL", "llama3.2:3b"),
    "whisper_model": os.environ.get("WHISPER_MODEL", "tiny"),
    "vad_threshold": 0.5,
    "screenshot_interval": int(os.environ.get("SCREENSHOT_INTERVAL", "12")),
    "gesture_confidence": float(os.environ.get("GESTURE_CONFIDENCE", "0.7")),
    "webhook_port": int(os.environ.get("WEBHOOK_PORT", "9003")),
    # Speed defaults — local-first auto route
    "max_tokens": int(os.environ.get("ASTRA_MAX_TOKENS", "256")),
    "temperature": float(os.environ.get("ASTRA_TEMPERATURE", "0.4")),
    "fast_mode": os.environ.get("ASTRA_FAST_MODE", "1").strip().lower() in ("1", "true", "yes"),
    "route": (os.environ.get("ASTRA_ROUTE") or "auto").strip().lower(),  # auto|local|cloud
}

# ── NLP + CV engines (v2 modules) ─────────────────────────────────────────────
from nlp import NLPEngine, build_system_prompt, classify_intent  # noqa: E402
from cv import VisionEngineV2  # noqa: E402
from rag import RAGEngine  # noqa: E402
from mcp_client import MCPManager  # noqa: E402

ASTRA_SYSTEM_PROMPT = build_system_prompt("default", "chat")

# ── Speech ────────────────────────────────────────────────────────────────────
class SpeechEngine:
    def __init__(self, event_cb):
        self.event_cb = event_cb
        self.running = False
        self.whisper_model = None
        # Lazy load on first speech loop — faster boot

    def _load_whisper(self):
        if self.whisper_model:
            return True
        whisper = try_import("whisper")
        if whisper:
            try:
                self.whisper_model = whisper.load_model(CONFIG["whisper_model"])
                self.event_cb({"type": "speech_ready", "msg": "Whisper loaded"})
                return True
            except Exception as e:
                self.event_cb({"type": "warn", "msg": f"Whisper load failed: {e}"})
        return False

    def start_vad_loop(self):
        sd = try_import("sounddevice")
        np = try_import("numpy")
        if not sd or not np:
            self.event_cb({"type": "warn", "msg": "Speech engine unavailable. Install: pip install sounddevice numpy openai-whisper"})
            return
        if not self._load_whisper():
            self.event_cb({"type": "warn", "msg": "Whisper not ready — PTT will be limited"})
            return
        SAMPLE_RATE = 16000
        CHUNK = 1024
        SILENCE_THRESH = 0.01
        MIN_SPEECH_SECS = 0.8
        self.running = True
        self.event_cb({"type": "speech_listening", "msg": "VAD active — no wake word needed"})
        buffer = []
        speaking = False
        silence_count = 0

        def audio_cb(indata, frames, time_info, status):
            nonlocal speaking, silence_count, buffer
            chunk = indata[:, 0]
            rms = float(np.sqrt(np.mean(chunk ** 2)))
            if rms > SILENCE_THRESH:
                speaking = True
                silence_count = 0
                buffer.extend(chunk.tolist())
            elif speaking:
                silence_count += 1
                buffer.extend(chunk.tolist())
                if silence_count > (SAMPLE_RATE / CHUNK) * 1.2:
                    if len(buffer) > SAMPLE_RATE * MIN_SPEECH_SECS:
                        audio_arr = np.array(buffer, dtype=np.float32)
                        threading.Thread(target=self._transcribe, args=(audio_arr,), daemon=True).start()
                    buffer = []
                    speaking = False
                    silence_count = 0

        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, blocksize=CHUNK, callback=audio_cb):
            while self.running:
                time.sleep(0.1)

    def _transcribe(self, audio_arr):
        try:
            result = self.whisper_model.transcribe(audio_arr, language="en", fp16=False)
            text = result["text"].strip()
            if text and len(text) > 2:
                self.event_cb({"type": "speech_transcript", "text": text})
        except Exception as e:
            self.event_cb({"type": "warn", "msg": f"Transcription error: {e}"})

    def stop(self):
        self.running = False


class MemoryLayer:
    """Episodic context + semantic notes + goals + audit."""

    def __init__(self):
        self.db_path = os.path.join(os.path.dirname(__file__), "../../models/memory.json")
        self.data = self._load()

    def _default(self):
        return {
            "goals": [],
            "tasks": [],
            "projects": [],
            "preferences": {},
            "context": [],
            "webhooks": [],
            "notes": [],
            "audit": [],
            "facts": [],
        }

    def _load(self):
        try:
            with open(self.db_path) as f:
                data = json.load(f)
            base = self._default()
            base.update(data or {})
            return base
        except Exception:
            return self._default()

    def save(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with open(self.db_path, "w") as f:
            json.dump(self.data, f, indent=2)

    def add_context(self, role, text):
        self.data.setdefault("context", []).append(
            {"role": role, "text": text, "ts": datetime.now().isoformat()}
        )
        if len(self.data["context"]) > 120:
            self.data["context"] = self.data["context"][-120:]
        self.save()

    def get_context_str(self, n=12):
        recent = self.data.get("context", [])[-n:]
        parts = [f"{c['role'].upper()}: {c['text']}" for c in recent]
        facts = self.data.get("facts") or []
        if facts:
            parts.insert(0, "FACTS: " + "; ".join(facts[-12:]))
        notes = self.data.get("notes") or []
        if notes:
            parts.insert(0, "NOTES: " + " | ".join(n.get("text", "")[:80] for n in notes[-5:]))
        return "\n".join(parts)

    def add_note(self, text, kind="note"):
        self.data.setdefault("notes", []).append(
            {"text": text, "kind": kind, "ts": datetime.now().isoformat()}
        )
        self.data["notes"] = self.data["notes"][-80:]
        self.save()

    def add_fact(self, text):
        facts = self.data.setdefault("facts", [])
        if text and text not in facts:
            facts.append(text[:200])
        self.data["facts"] = facts[-40:]
        self.save()

    def add_goal(self, text):
        self.data.setdefault("goals", []).append(
            {"text": text, "done": False, "ts": datetime.now().isoformat()}
        )
        self.data["goals"] = self.data["goals"][-30:]
        self.save()

    def audit(self, action, detail=""):
        self.data.setdefault("audit", []).append(
            {"action": action, "detail": detail[:300], "ts": datetime.now().isoformat()}
        )
        self.data["audit"] = self.data["audit"][-100:]
        self.save()

    def search(self, query: str, limit: int = 12):
        q = (query or "").lower()
        hits = []
        for c in reversed(self.data.get("context") or []):
            if q in (c.get("text") or "").lower():
                hits.append({"type": "context", **c})
            if len(hits) >= limit:
                break
        for n in reversed(self.data.get("notes") or []):
            if q in (n.get("text") or "").lower():
                hits.append({"type": "note", **n})
            if len(hits) >= limit:
                break
        return hits

    def dump(self):
        return {
            "goals": self.data.get("goals", [])[-10:],
            "notes": self.data.get("notes", [])[-15:],
            "facts": self.data.get("facts", [])[-15:],
            "audit": self.data.get("audit", [])[-20:],
            "context_tail": self.data.get("context", [])[-8:],
        }

    def log_webhook(self, event):
        self.data.setdefault("webhooks", []).append({
            **event,
            "ts": datetime.now().isoformat(),
        })
        self.data["webhooks"] = self.data["webhooks"][-50:]
        self.save()


# ── Main Brain ────────────────────────────────────────────────────────────────
class ASTRABrain:
    def __init__(self):
        self.nlp = NLPEngine(CONFIG, emit=self.emit)
        self.memory = MemoryLayer()
        self.rag = RAGEngine(emit=self.emit)
        self.mcp = MCPManager(emit=self.emit)
        self._whisper_model = None
        self.webhooks = None
        # Webhooks first — always available even if CV/speech fail
        self._start_webhooks()
        # Skip speech/vision objects entirely in fast mode (boot + stability)
        if CONFIG.get("fast_mode"):
            self.speech = None
            self.vision = None
            self.emit({"type": "info", "msg": "Fast mode: CV/speech backends deferred (use UI mic → WAV STT)"})
        else:
            try:
                self.speech = SpeechEngine(self.emit)
            except Exception as e:
                self.speech = None
                self.emit({"type": "warn", "msg": f"Speech engine init failed: {e}"})
            try:
                self.vision = VisionEngineV2(self.emit, config=CONFIG)
            except Exception as e:
                self.vision = None
                self.emit({"type": "warn", "msg": f"Vision engine init failed: {e}"})
        self._start_threads()
        # Surface RAG stats + start enabled MCP servers
        try:
            self.emit({"type": "rag_stats", **self.rag.stats()})
        except Exception:
            pass
        try:
            self.mcp.start_enabled()
            self.emit({"type": "mcp_status", **self.mcp.status()})
        except Exception as e:
            self.emit({"type": "warn", "msg": f"MCP start: {e}"})

    def emit(self, event: dict):
        print(json.dumps(event), flush=True)

    def _start_webhooks(self):
        try:
            from webhooks.engine import ASTRAWebhookServer
            port = CONFIG.get("webhook_port", 9003)
            self.webhooks = ASTRAWebhookServer(event_cb=self._on_webhook, port=port)
            self.webhooks.start()
            # ready event emitted by server; also send endpoints list
            self.emit({
                "type": "webhook_endpoints",
                "port": port,
                "endpoints": [
                    "/health", "/github", "/stripe", "/discord",
                    "/notion", "/vercel", "/trading", "/custom/*", "/astra",
                ],
            })
        except Exception as e:
            self.emit({"type": "warn", "msg": f"Webhook engine failed to start: {e}"})

    def _on_webhook(self, event: dict):
        """Forward webhook events to UI and log."""
        self.emit(event)
        if event.get("type") == "webhook_in":
            self.memory.log_webhook({
                "path": event.get("path"),
                "event": event.get("event"),
                "summary": str(event.get("payload", {}))[:200],
            })
            # Optional auto-reply via Grok for /astra path
            if event.get("path") == "/astra":
                payload = event.get("payload") or {}
                text = payload.get("text") or payload.get("message") or ""
                if text:
                    def _reply():
                        try:
                            reply = self.nlp.route(f"Webhook request: {text}", "grok")
                            self.emit({
                                "type": "webhook_reply",
                                "path": "/astra",
                                "request": text,
                                "reply": reply,
                            })
                        except Exception as ex:
                            self.emit({"type": "warn", "msg": f"Webhook Grok reply failed: {ex}"})
                    threading.Thread(target=_reply, daemon=True).start()

    def _start_threads(self):
        # CV/webcam and speech native libs often crash (0xC0000005) on Windows.
        # Keep chat/LLM solid by default; opt in via env if needed.
        enable_speech = os.environ.get("ASTRA_ENABLE_SPEECH", "0").strip().lower() in ("1", "true", "yes")
        enable_cv = os.environ.get("ASTRA_ENABLE_CV", "0").strip().lower() in ("1", "true", "yes")

        def _later():
            time.sleep(1.5)
            if enable_speech and self.speech:
                try:
                    threading.Thread(target=self.speech.start_vad_loop, daemon=True).start()
                except Exception as e:
                    self.emit({"type": "warn", "msg": f"Speech loop failed: {e}"})
            elif self.speech:
                self.emit({"type": "info", "msg": "Speech idle (set ASTRA_ENABLE_SPEECH=1 to enable)"})
            if enable_cv and self.vision:
                try:
                    self.vision.running = True
                    threading.Thread(target=self.vision.start_webcam_loop, daemon=True).start()

                    def _nlp_screen(prompt, image_b64=None):
                        return self.nlp.complete(
                            prompt, mode="default", image_b64=image_b64, prefer="auto"
                        )

                    threading.Thread(
                        target=self.vision.start_screen_loop,
                        args=(_nlp_screen,),
                        daemon=True,
                    ).start()
                except Exception as e:
                    self.emit({"type": "warn", "msg": f"Vision loop failed: {e}"})
            elif self.vision:
                self.emit({"type": "info", "msg": "Vision idle (set ASTRA_ENABLE_CV=1 to enable)"})
        threading.Thread(target=_later, daemon=True).start()

        cp = CONFIG.get("cloud_provider") or "none"
        if cp == "nvidia" and CONFIG.get("xai_key"):
            provider = "NVIDIA NIM"
        elif cp == "grok" and CONFIG.get("xai_key"):
            provider = "Grok"
        elif cp == "openai" and CONFIG.get("xai_key"):
            provider = "OpenAI"
        elif CONFIG.get("anthropic_key"):
            provider = "Claude"
        else:
            provider = "Ollama/demo"
        if CONFIG.get("anthropic_key") and not CONFIG.get("xai_key"):
            provider = "Claude"
        model = CONFIG.get("xai_model") if CONFIG.get("xai_key") else CONFIG.get("ollama_model")
        if cp == "openai" and str(model).startswith("grok"):
            model = "gpt-4o"
        cv_backend = getattr(self.vision, "backend", "none") if self.vision else "none"
        self.emit({
            "type": "brain_ready",
            "msg": f"ASTRA Brain online. NLP v2 + CV v2. Primary LLM: {provider}",
            "provider": provider,
            "model": model,
            "has_xai": bool(CONFIG.get("xai_key")),
            "has_claude": bool(CONFIG.get("anthropic_key")),
            "cloud_provider": cp,
            "cv_backend": cv_backend,
            "nlp_version": 2,
            "cv_version": 2,
        })
        self._emit_health()

    def _emit_health(self):
        import urllib.request
        ollama_ok = False
        try:
            with urllib.request.urlopen(f"{CONFIG['ollama_url']}/api/tags", timeout=2) as r:
                ollama_ok = r.status == 200
        except Exception:
            pass
        cv_ok = bool(
            self.vision
            and getattr(self.vision, "backend", "none") not in ("none", "", None)
        )
        self.emit({
            "type": "health",
            "ts": datetime.now().isoformat(),
            "subsystems": {
                "cloud_llm": bool(CONFIG.get("xai_key") or CONFIG.get("anthropic_key")),
                "cloud_provider": CONFIG.get("cloud_provider"),
                "claude": bool(CONFIG.get("anthropic_key")),
                "ollama": ollama_ok,
                "webhooks": bool(self.webhooks),
                "speech": bool(self.speech and getattr(self.speech, "whisper_model", None)),
                "vision": cv_ok,
                "cv_backend": getattr(self.vision, "backend", "none") if self.vision else "none",
                "nlp": True,
                "memory": True,
                "agent_tools": True,
            },
            "webhook_port": CONFIG.get("webhook_port", 9003),
            "model": CONFIG.get("xai_model"),
        })

    def handle_input(self, data: dict):
        msg_type = data.get("type", "")

        if msg_type == "chat":
            prompt = data.get("text", "")
            mode = data.get("mode", "default")
            use_agent = data.get("agent", False)  # default off for speed
            source = data.get("source") or "astra"
            t0 = time.time()

            # Persist user turn into episodic + RAG (always track)
            self.memory.add_context("user", prompt)
            self.memory.audit("chat", prompt[:120])
            self.rag.add_turn("user", prompt, source=source)

            # Fast intent (rules only — no LLM)
            analysis = self.nlp.analyze(
                prompt,
                mode=mode if mode not in ("local", "claude", "grok", "tools", "chat_only") else "default",
            )
            intent = analysis.get("intent") or "chat"

            # RAG: skip for tiny greetings; never put raw memory into the user turn
            # (small local models echo "RELEVANT MEMORY" otherwise)
            pl = (prompt or "").strip().lower()
            is_greeting = pl in ("hi", "hey", "hello", "yo", "sup", "hola", "ok", "okay", "thanks", "thank you")
            hits = [] if is_greeting else self.rag.retrieve(prompt, k=3, min_score=0.18)
            # Drop junk / self-echo memories
            hits = [
                h for h in hits
                if h.get("text")
                and "RELEVANT MEMORY" not in (h.get("text") or "")
                and "RECENT:" not in (h.get("text") or "")
                and len((h.get("text") or "").strip()) > 2
            ]
            self.emit({"type": "rag_hits", "hits": hits, "stats": self.rag.stats()})

            mem_bits = [self.rag.system_addon()]
            if hits:
                mem_bits.append(
                    "Silent background facts (never quote or dump these; answer the user only):\n"
                    + "\n".join(f"- ({h.get('source')}) {h.get('text')[:160]}" for h in hits)
                )
            # Only last 2 clean turns of recent chat (not the whole polluted history)
            recent_clean = []
            for c in (self.memory.data.get("context") or [])[-8:]:
                t = (c.get("text") or "").strip()
                if not t or "RELEVANT MEMORY" in t or "Falling back to" in t or "Cloud LLM error" in t:
                    continue
                if len(t) > 400:
                    t = t[:400] + "…"
                recent_clean.append(f"{c.get('role','?').upper()}: {t}")
            if recent_clean and not is_greeting:
                mem_bits.append("Last turns:\n" + "\n".join(recent_clean[-4:]))

            system = build_system_prompt(
                mode if mode in (
                    "ENGINEER MODE", "STUDENT MODE", "FOUNDER MODE",
                    "FOCUS LOCK", "TRADING MODE", "RECOVERY MODE", "default",
                ) else "default",
                intent,
                extra="\n".join(mem_bits)
                + "\nReply in plain natural language only. Never print memory dumps, scores, or labels like RELEVANT MEMORY.",
            )
            # User message is ONLY the user's text — no context prefix
            ctx = ""

            # Only use tools when user clearly wants agent work
            force_tools = intent == "agent_tools" or mode in ("tools", "agent")
            agent_mode = "tools" if force_tools else ("chat_only" if mode == "default" else mode)
            if mode in ("tools", "agent", "local", "claude", "grok", "chat_only"):
                agent_mode = mode

            self.emit({
                "type": "chat_start",
                "mode": mode,
                "intent": intent,
                "model": CONFIG.get("xai_model"),
            })
            try:
                from agent import run_agent_chat
                response = run_agent_chat(
                    prompt=prompt,
                    system=system,
                    config=CONFIG,
                    context=ctx,
                    mode=agent_mode,
                    emit=self.emit,
                    use_tools=bool(use_agent and force_tools),
                    stream=True,
                )
            except Exception as e:
                self.emit({"type": "warn", "msg": f"Agent path failed: {e}"})
                response = self.nlp.complete(
                    prompt, mode=mode if mode not in ("local", "claude", "grok") else "default",
                    context="", prefer="auto" if mode == "default" else mode,
                )
                self.emit({"type": "chat_delta", "text": response})

            # Sanitize model echo bugs
            response = (response or "").strip()
            if response.startswith("RELEVANT MEMORY") or response.startswith("RECENT:") or "RELEVANT MEMORY (RAG)" in response[:80]:
                # Model echoed prompt — give a clean short reply instead of storing garbage
                response = "Hey — I'm here. What do you need?"
                self.emit({"type": "chat_delta", "text": response})

            # Track assistant + continual learning (skip garbage)
            if response and "RELEVANT MEMORY" not in response:
                self.memory.add_context("astra", response)
                self.rag.add_turn("assistant", response, source=source)
                try:
                    self.rag.learn_from_exchange(prompt, response, source=source)
                    self.rag.flush()
                except Exception as le:
                    self.emit({"type": "warn", "msg": f"Learn step: {le}"})

            ms = int((time.time() - t0) * 1000)
            used_provider = CONFIG.pop("_last_provider", None) or CONFIG.get("cloud_provider") or "local"
            used_model = CONFIG.pop("_last_model", None) or CONFIG.get("xai_model")
            used_ms = CONFIG.pop("_last_ms", None) or ms
            self.emit({
                "type": "chat_response",
                "text": response,
                "provider": used_provider,
                "intent": intent,
                "ms": used_ms,
                "model": used_model,
                "rag_hits": len(hits),
                "route": CONFIG.get("route") or "auto",
            })

        elif msg_type == "mission":
            mid = data.get("id") or data.get("mission_id") or ""
            self.memory.audit("mission", mid)
            try:
                from missions import run_mission, MISSIONS
                if mid == "list":
                    self.emit({"type": "missions_list", "missions": MISSIONS})
                else:
                    self.emit({"type": "chat_start", "mode": "mission"})
                    text = run_mission(mid, emit=self.emit)
                    for i in range(0, len(text), 60):
                        self.emit({"type": "chat_delta", "text": text[i:i+60]})
                    self.emit({"type": "chat_response", "text": text, "provider": "mission"})
                    self.memory.add_context("astra", text[:500])
            except Exception as e:
                self.emit({"type": "warn", "msg": f"Mission failed: {e}"})

        elif msg_type == "list_missions":
            try:
                from missions import MISSIONS
                self.emit({"type": "missions_list", "missions": MISSIONS})
            except Exception as e:
                self.emit({"type": "warn", "msg": str(e)})

        elif msg_type == "memory_get":
            self.emit({"type": "memory_dump", "data": self.memory.dump()})

        elif msg_type == "memory_add":
            text = data.get("text", "")
            kind = data.get("kind", "note")
            if kind == "fact":
                self.memory.add_fact(text)
            elif kind == "goal":
                self.memory.add_goal(text)
            else:
                self.memory.add_note(text, kind)
            self.emit({"type": "memory_dump", "data": self.memory.dump()})

        elif msg_type == "memory_search":
            hits = self.memory.search(data.get("query", ""))
            self.emit({"type": "memory_search_results", "hits": hits})

        elif msg_type == "health":
            self._emit_health()

        elif msg_type == "set_config":
            cfg = data.get("config", {})
            # map UI fields
            if "xai_key" in cfg:
                CONFIG["xai_key"] = cfg["xai_key"] or CONFIG["xai_key"]
                if cfg["xai_key"]:
                    # re-detect provider from key prefix
                    k = str(cfg["xai_key"])
                    if k.startswith("nvapi-"):
                        CONFIG["cloud_provider"] = "nvidia"
                        CONFIG["xai_base"] = "https://integrate.api.nvidia.com/v1"
                        if not CONFIG.get("xai_model") or str(CONFIG.get("xai_model", "")).startswith("grok"):
                            CONFIG["xai_model"] = "meta/llama-3.2-3b-instruct"
                    elif k.startswith("xai-"):
                        CONFIG["cloud_provider"] = "grok"
                        CONFIG["xai_base"] = "https://api.x.ai/v1"
                    elif k.startswith("sk-"):
                        CONFIG["cloud_provider"] = "openai"
                        CONFIG["xai_base"] = "https://api.openai.com/v1"
            if "xai_model" in cfg:
                CONFIG["xai_model"] = cfg["xai_model"]
            if "anthropic_key" in cfg:
                CONFIG["anthropic_key"] = cfg["anthropic_key"]
            # Persist key to .env (gitignored) for restarts
            if cfg.get("xai_key"):
                try:
                    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
                    lines = []
                    if env_path.exists():
                        lines = env_path.read_text(encoding="utf-8").splitlines()
                    out, found = [], False
                    for line in lines:
                        if line.startswith("XAI_API_KEY="):
                            out.append(f"XAI_API_KEY={cfg['xai_key']}")
                            found = True
                        else:
                            out.append(line)
                    if not found:
                        out.append(f"XAI_API_KEY={cfg['xai_key']}")
                    env_path.write_text("\n".join(out) + "\n", encoding="utf-8")
                except Exception as e:
                    self.emit({"type": "warn", "msg": f"Could not write .env: {e}"})
            CONFIG.update({k: v for k, v in cfg.items() if k in CONFIG or k in ("xai_key", "xai_model", "anthropic_key")})
            self.emit({"type": "config_updated", "has_xai": bool(CONFIG.get("xai_key"))})
            self._emit_health()

        elif msg_type == "ping":
            self.emit({
                "type": "pong",
                "ts": datetime.now().isoformat(),
                "has_xai": bool(CONFIG.get("xai_key")),
                "webhook_port": CONFIG.get("webhook_port", 9003),
            })

        elif msg_type == "webhook_test":
            path = data.get("path", "/custom/test")
            payload = data.get("payload") or {"source": "astra-ui", "test": True, "ts": datetime.now().isoformat()}
            self._on_webhook({
                "type": "webhook_in",
                "path": path,
                "payload": payload,
                "event": f"test{path.replace('/', '.')}",
            })
            self.emit({"type": "webhook_test_ok", "path": path})

        elif msg_type == "webhook_out":
            url = data.get("url", "")
            payload = data.get("payload") or {}
            if self.webhooks and url:
                ok = self.webhooks.trigger(url, payload)
                self.emit({"type": "webhook_out_result", "ok": ok, "url": url})
            else:
                self.emit({"type": "warn", "msg": "Outgoing webhook missing URL or engine offline"})

        elif msg_type == "get_webhook_log":
            self.emit({
                "type": "webhook_log",
                "items": self.memory.data.get("webhooks", [])[-30:],
            })

        elif msg_type == "ptt_start":
            self.emit({"type": "speech_listening", "msg": "PTT — speak now (if Whisper installed)"})

        elif msg_type == "rag_stats":
            self.emit({"type": "rag_stats", **self.rag.stats()})

        elif msg_type == "rag_search":
            q = data.get("query") or ""
            hits = self.rag.retrieve(q, k=int(data.get("k") or 8))
            self.emit({"type": "rag_hits", "hits": hits, "query": q})

        elif msg_type == "rag_import_text":
            try:
                n = self.rag.import_text_blob(data.get("text") or "", source=data.get("source") or "paste")
                self.emit({"type": "rag_import", "count": n, "source": data.get("source") or "paste", **self.rag.stats()})
            except Exception as e:
                self.emit({"type": "error", "msg": f"RAG import failed: {e}"})

        elif msg_type == "rag_import_file":
            try:
                n = self.rag.import_json_file(data.get("path") or "", source=data.get("source") or "import")
                self.emit({"type": "rag_import", "count": n, "source": data.get("source") or "import", **self.rag.stats()})
            except Exception as e:
                self.emit({"type": "error", "msg": f"RAG file import failed: {e}"})

        elif msg_type == "rag_add_fact":
            self.rag.add_fact(data.get("text") or "", source=data.get("source") or "user")
            self.emit({"type": "rag_stats", **self.rag.stats()})

        elif msg_type == "learn_external":
            # Track a conversation turn from another AI (user + their reply)
            u = data.get("user") or ""
            a = data.get("assistant") or ""
            src = data.get("source") or "other_ai"
            if u:
                self.rag.add_turn("user", u, source=src)
            if a:
                self.rag.add_turn("assistant", a, source=src)
            if u and a:
                self.rag.learn_from_exchange(u, a, source=src)
            self.rag.flush()
            self.emit({"type": "rag_stats", **self.rag.stats(), "msg": "External conversation absorbed"})

        elif msg_type == "transcribe":
            # Renderer MediaRecorder WAV (base64) → local STT
            self._handle_transcribe(data)

        elif msg_type == "mcp_status":
            try:
                self.emit({"type": "mcp_status", **self.mcp.status()})
            except Exception as e:
                self.emit({"type": "error", "msg": str(e)})

        elif msg_type == "mcp_reload":
            try:
                self.mcp.stop_all()
                self.mcp.reload()
                self.mcp.start_enabled()
                self.emit({"type": "mcp_status", **self.mcp.status(), "msg": "MCP reloaded"})
            except Exception as e:
                self.emit({"type": "error", "msg": f"MCP reload failed: {e}"})

        elif msg_type == "mcp_list_tools":
            try:
                tools = self.mcp.all_tools()
                self.emit({"type": "mcp_tools", "tools": tools})
            except Exception as e:
                self.emit({"type": "error", "msg": str(e)})

        elif msg_type == "mcp_call":
            try:
                result = self.mcp.call(
                    data.get("tool") or data.get("name") or "",
                    arguments=data.get("arguments") or data.get("args") or {},
                    server=data.get("server"),
                )
                self.emit({"type": "mcp_result", "tool": data.get("tool"), "result": result})
            except Exception as e:
                self.emit({"type": "error", "msg": f"MCP call failed: {e}"})

        elif msg_type == "memory_clear_chat":
            # Wipe polluted recent chat context (keeps RAG facts)
            self.memory.data["context"] = []
            self.memory.save()
            self.emit({"type": "memory_dump", "data": self.memory.dump(), "msg": "Chat context cleared"})

    def _handle_transcribe(self, data: dict):
        """Transcribe base64 audio from the renderer (WAV preferred)."""
        import base64
        import tempfile

        b64 = data.get("audio_b64") or ""
        if not b64:
            self.emit({"type": "speech_error", "msg": "No audio received"})
            return
        try:
            raw = base64.b64decode(b64)
        except Exception as e:
            self.emit({"type": "speech_error", "msg": f"Bad audio data: {e}"})
            return

        suffix = ".wav"
        mime = (data.get("mime") or "audio/wav").lower()
        if "webm" in mime:
            suffix = ".webm"
        elif "ogg" in mime:
            suffix = ".ogg"
        elif "mpeg" in mime or "mp3" in mime:
            suffix = ".mp3"

        path = None
        text = ""
        err = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
                f.write(raw)
                path = f.name

            # 1) openai-whisper
            try:
                import whisper  # type: ignore
                model_name = CONFIG.get("whisper_model") or "tiny"
                if not hasattr(self, "_whisper_model") or self._whisper_model is None:
                    self.emit({"type": "speech_listening", "msg": f"Loading Whisper {model_name}…"})
                    self._whisper_model = whisper.load_model(model_name)
                result = self._whisper_model.transcribe(path, language="en", fp16=False)
                text = (result.get("text") or "").strip()
            except Exception as e1:
                err = f"whisper: {e1}"
                # 2) SpeechRecognition + Google free web API (needs wav)
                try:
                    import speech_recognition as sr  # type: ignore
                    r = sr.Recognizer()
                    with sr.AudioFile(path) as source:
                        audio = r.record(source)
                    text = r.recognize_google(audio)
                except Exception as e2:
                    err = f"{err}; sr: {e2}"

            if text:
                self.emit({"type": "speech_transcript", "text": text})
                self.emit({"type": "speech_ready", "msg": "Voice STT OK"})
            else:
                self.emit({
                    "type": "speech_error",
                    "msg": (
                        "Could not transcribe. Install: pip install openai-whisper "
                        "OR pip install SpeechRecognition  "
                        f"({err or 'no engine'})"
                    ),
                })
        except Exception as e:
            self.emit({"type": "speech_error", "msg": str(e)})
        finally:
            if path:
                try:
                    os.unlink(path)
                except Exception:
                    pass

    def run(self):
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                self.handle_input(data)
            except json.JSONDecodeError:
                self.emit({"type": "error", "msg": f"Invalid JSON: {line}"})


if __name__ == "__main__":
    try:
        brain = ASTRABrain()
        brain.run()
    except Exception as e:
        # Always emit something Electron can surface
        print(json.dumps({"type": "error", "msg": f"Brain fatal: {e}"}), flush=True)
        raise
