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
        for line in env_path.read_text(encoding="utf-8").splitlines():
            t = line.strip()
            if not t or t.startswith("#") or "=" not in t:
                continue
            k, v = t.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
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
    True xAI keys (xai-…) → Grok on api.x.ai.
    OpenAI-style keys (sk-…) → OpenAI-compatible chat (user-supplied).
    """
    raw = (
        os.environ.get("XAI_API_KEY")
        or os.environ.get("GROK_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or ""
    ).strip()
    base = (os.environ.get("XAI_BASE_URL") or "").rstrip("/")
    model = os.environ.get("XAI_MODEL") or os.environ.get("OPENAI_MODEL") or ""

    if not raw:
        return {"key": "", "base": "https://api.x.ai/v1", "model": "grok-4.5", "provider": "none"}

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
    "ollama_url": os.environ.get("OLLAMA_URL", "http://localhost:11434"),
    "ollama_model": os.environ.get("OLLAMA_MODEL", "llama3.1:8b"),
    "whisper_model": os.environ.get("WHISPER_MODEL", "tiny"),
    "vad_threshold": 0.5,
    "screenshot_interval": int(os.environ.get("SCREENSHOT_INTERVAL", "10")),
    "gesture_confidence": 0.75,
    "webhook_port": int(os.environ.get("WEBHOOK_PORT", "9003")),
}

# ── System prompt ─────────────────────────────────────────────────────────────
ASTRA_SYSTEM_PROMPT = """You are ASTRA, an elite desktop AI operating system powered by Grok.
You are calm, sharp, concise, and execution-oriented.
You help with coding, research, trading, studying, and productivity.
Never be verbose. Always be actionable. Respond like a mission-critical AI assistant.
When relevant, mention webhook or automation hooks the user can use."""

# ── NLP Router (Grok primary) ─────────────────────────────────────────────────
class NLPRouter:
    def __init__(self):
        self.anthropic = None
        self._init_anthropic()

    def _init_anthropic(self):
        try:
            import anthropic
            if CONFIG.get("anthropic_key"):
                self.anthropic = anthropic.Anthropic(api_key=CONFIG["anthropic_key"])
        except ImportError:
            pass

    def route(self, prompt: str, mode: str = "default", image_b64: str = None) -> str:
        """Route: local → Ollama; cloud/default → Grok → Claude → Ollama."""
        if mode == "local":
            return self._ollama(prompt)

        if mode in ("default", "cloud", "grok") or not mode:
            if CONFIG.get("xai_key"):
                try:
                    return self._grok(prompt, image_b64)
                except Exception as e:
                    print(json.dumps({"type": "warn", "msg": f"Grok API failed, trying fallback: {e}"}), flush=True)
            if CONFIG.get("anthropic_key") and self.anthropic:
                try:
                    return self._claude(prompt, image_b64)
                except Exception as e:
                    print(json.dumps({"type": "warn", "msg": f"Claude failed, falling back to Ollama: {e}"}), flush=True)
            return self._ollama(prompt)

        if mode == "claude" and self.anthropic:
            try:
                return self._claude(prompt, image_b64)
            except Exception as e:
                return f"[Claude error: {e}]"

        return self._ollama(prompt)

    def _grok(self, prompt: str, image_b64: str = None) -> str:
        """Cloud LLM via OpenAI-compatible chat completions (Grok xAI or OpenAI)."""
        import urllib.request
        import urllib.error

        if not CONFIG.get("xai_key"):
            raise RuntimeError("XAI_API_KEY / OPENAI_API_KEY not set")

        content = []
        if image_b64:
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{image_b64}"},
            })
            content.append({"type": "text", "text": prompt})
            user_content = content
        else:
            user_content = prompt

        model = CONFIG.get("xai_model") or "grok-4.5"
        # If key is OpenAI-style but model is still grok-*, swap to gpt-4o
        if CONFIG.get("cloud_provider") == "openai" and str(model).startswith("grok"):
            model = "gpt-4o"

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": ASTRA_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.7,
            "max_tokens": 1024,
        }
        body = json.dumps(payload).encode()
        base = CONFIG["xai_base"].rstrip("/")
        req = urllib.request.Request(
            f"{base}/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {CONFIG['xai_key']}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            err_body = e.read().decode(errors="replace")[:400]
            raise RuntimeError(f"HTTP {e.code}: {err_body}") from e

        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(f"Empty cloud response: {str(data)[:200]}")
        msg = choices[0].get("message") or {}
        text = msg.get("content") or ""
        if not text:
            raise RuntimeError("Cloud LLM returned empty content")
        return text

    def _claude(self, prompt: str, image_b64: str = None) -> str:
        if not self.anthropic:
            return self._ollama(prompt)
        msgs = []
        if image_b64:
            msgs.append({"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image_b64}},
                {"type": "text", "text": prompt},
            ]})
        else:
            msgs.append({"role": "user", "content": prompt})
        resp = self.anthropic.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=ASTRA_SYSTEM_PROMPT,
            messages=msgs,
        )
        return resp.content[0].text

    def _ollama(self, prompt: str) -> str:
        try:
            import urllib.request
            payload = json.dumps({
                "model": CONFIG["ollama_model"],
                "prompt": f"{ASTRA_SYSTEM_PROMPT}\n\nUser: {prompt}\nASTRA:",
                "stream": False,
            }).encode()
            req = urllib.request.Request(
                f"{CONFIG['ollama_url']}/api/generate",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read())
                return data.get("response", "No response from Ollama.")
        except Exception as e:
            return (
                f"[No cloud/local model available: {e}. "
                f"Set XAI_API_KEY for Grok, or run: ollama pull {CONFIG['ollama_model']}]"
            )

# ── Speech / Vision (unchanged core) ──────────────────────────────────────────
class SpeechEngine:
    def __init__(self, event_cb):
        self.event_cb = event_cb
        self.running = False
        self.whisper_model = None
        self._load_whisper()

    def _load_whisper(self):
        whisper = try_import("whisper")
        if whisper:
            try:
                self.whisper_model = whisper.load_model(CONFIG["whisper_model"])
                self.event_cb({"type": "speech_ready", "msg": "Whisper loaded"})
            except Exception as e:
                self.event_cb({"type": "warn", "msg": f"Whisper load failed: {e}"})

    def start_vad_loop(self):
        sd = try_import("sounddevice")
        np = try_import("numpy")
        if not sd or not np or not self.whisper_model:
            self.event_cb({"type": "warn", "msg": "Speech engine unavailable. Install: pip install sounddevice numpy openai-whisper"})
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


class VisionEngine:
    GESTURES = {
        "FIST": "gesture_focus_lock",
        "OPEN_HAND": "gesture_mode_switch",
        "PEACE": "gesture_deep_work",
        "THUMBS_UP": "gesture_confirm",
        "POINTING_UP": "gesture_scroll_up",
        "POINTING_DOWN": "gesture_scroll_down",
    }

    def __init__(self, event_cb):
        self.event_cb = event_cb
        self.running = False
        self.mp = None
        self.mp_hands = None
        self.mp_face = None
        self._load_mediapipe()

    def _load_mediapipe(self):
        mp = try_import("mediapipe")
        if not mp:
            return
        try:
            if not hasattr(mp, "solutions"):
                self.event_cb({"type": "warn", "msg": "MediaPipe install incomplete (no solutions). Reinstall: pip install mediapipe"})
                return
            self.mp = mp
            self.mp_hands = mp.solutions.hands.Hands(
                static_image_mode=False,
                max_num_hands=1,
                min_detection_confidence=CONFIG["gesture_confidence"],
                min_tracking_confidence=0.5,
            )
            self.mp_face = mp.solutions.face_detection.FaceDetection(
                model_selection=0, min_detection_confidence=0.6
            )
            self.event_cb({"type": "cv_ready", "msg": "MediaPipe loaded — CV online"})
        except Exception as e:
            self.mp = None
            self.event_cb({"type": "warn", "msg": f"MediaPipe init failed: {e}"})

    def start_webcam_loop(self):
        cv2 = try_import("cv2")
        np = try_import("numpy")
        if not cv2 or not np or not self.mp:
            self.event_cb({"type": "warn", "msg": "CV unavailable. Install: pip install mediapipe opencv-python"})
            return
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            self.event_cb({"type": "warn", "msg": "Webcam not found"})
            return
        self.running = True
        self.event_cb({"type": "webcam_active", "msg": "Webcam online — presence + gesture detection active"})
        last_gesture = None
        gesture_hold = 0
        presence_state = False
        while self.running:
            ret, frame = cap.read()
            if not ret:
                break
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            face_results = self.mp_face.process(rgb)
            face_detected = bool(face_results.detections)
            if face_detected != presence_state:
                presence_state = face_detected
                self.event_cb({"type": "presence", "present": presence_state})
                if not face_detected:
                    self.event_cb({"type": "away_detected", "msg": "User away — pausing focus timer"})
            hand_results = self.mp_hands.process(rgb)
            if hand_results.multi_hand_landmarks:
                for hand_lm in hand_results.multi_hand_landmarks:
                    gesture = self._classify_gesture(hand_lm.landmark)
                    if gesture:
                        if gesture == last_gesture:
                            gesture_hold += 1
                            if gesture_hold == 5:
                                action = self.GESTURES.get(gesture)
                                if action:
                                    self.event_cb({"type": "gesture", "gesture": gesture, "action": action})
                        else:
                            last_gesture = gesture
                            gesture_hold = 0
            else:
                last_gesture = None
                gesture_hold = 0
            time.sleep(0.033)
        cap.release()

    def _classify_gesture(self, landmarks):
        lm = landmarks

        def tip_up(tip, pip):
            return lm[tip].y < lm[pip].y

        index_up = tip_up(8, 6)
        middle_up = tip_up(12, 10)
        ring_up = tip_up(16, 14)
        pinky_up = tip_up(20, 18)
        thumb_up = lm[4].y < lm[3].y
        fingers_up = sum([index_up, middle_up, ring_up, pinky_up])
        if fingers_up == 0 and not thumb_up:
            return "FIST"
        if fingers_up == 4 and thumb_up:
            return "OPEN_HAND"
        if index_up and middle_up and not ring_up and not pinky_up:
            return "PEACE"
        if thumb_up and not index_up and fingers_up == 0:
            return "THUMBS_UP"
        if index_up and not middle_up and not ring_up and not pinky_up:
            return "POINTING_UP" if lm[8].y < lm[5].y else "POINTING_DOWN"
        return None

    def start_screen_loop(self, nlp_router):
        pil = try_import("PIL")
        if not pil:
            self.event_cb({"type": "warn", "msg": "Screen awareness unavailable. Install: pip install Pillow"})
            return
        import PIL.ImageGrab as ImageGrab
        import io
        self.event_cb({"type": "screen_watch_active", "msg": "Screen awareness online"})
        while self.running:
            time.sleep(CONFIG["screenshot_interval"])
            try:
                screenshot = ImageGrab.grab()
                screenshot = screenshot.resize((1280, 720))
                buf = io.BytesIO()
                screenshot.save(buf, format="PNG")
                b64 = base64.b64encode(buf.getvalue()).decode()
                response = nlp_router.route(
                    "Analyze this screenshot. What is the user working on? Any suggestions? Be brief — 1-2 sentences.",
                    image_b64=b64,
                )
                self.event_cb({"type": "screen_insight", "text": response})
            except Exception:
                pass

    def stop(self):
        self.running = False


class MemoryLayer:
    def __init__(self):
        self.db_path = os.path.join(os.path.dirname(__file__), "../../models/memory.json")
        self.data = self._load()

    def _load(self):
        try:
            with open(self.db_path) as f:
                return json.load(f)
        except Exception:
            return {"goals": [], "tasks": [], "projects": [], "preferences": {}, "context": [], "webhooks": []}

    def save(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with open(self.db_path, "w") as f:
            json.dump(self.data, f, indent=2)

    def add_context(self, role, text):
        self.data["context"].append({"role": role, "text": text, "ts": datetime.now().isoformat()})
        if len(self.data["context"]) > 100:
            self.data["context"] = self.data["context"][-100:]
        self.save()

    def get_context_str(self, n=10):
        recent = self.data["context"][-n:]
        return "\n".join([f"{c['role'].upper()}: {c['text']}" for c in recent])

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
        self.nlp = NLPRouter()
        self.memory = MemoryLayer()
        self.webhooks = None
        # Webhooks first — always available even if CV/speech fail
        self._start_webhooks()
        try:
            self.speech = SpeechEngine(self.emit)
        except Exception as e:
            self.speech = None
            self.emit({"type": "warn", "msg": f"Speech engine init failed: {e}"})
        try:
            self.vision = VisionEngine(self.emit)
        except Exception as e:
            self.vision = None
            self.emit({"type": "warn", "msg": f"Vision engine init failed: {e}"})
        self._start_threads()

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
        # Defer heavy CV/speech so chat + webhooks come up fast
        def _later():
            time.sleep(2)
            if self.speech:
                try:
                    threading.Thread(target=self.speech.start_vad_loop, daemon=True).start()
                except Exception as e:
                    self.emit({"type": "warn", "msg": f"Speech loop failed: {e}"})
            if self.vision:
                try:
                    self.vision.running = True
                    threading.Thread(target=self.vision.start_webcam_loop, daemon=True).start()
                    threading.Thread(target=self.vision.start_screen_loop, args=(self.nlp,), daemon=True).start()
                except Exception as e:
                    self.emit({"type": "warn", "msg": f"Vision loop failed: {e}"})
        threading.Thread(target=_later, daemon=True).start()

        cp = CONFIG.get("cloud_provider") or "none"
        if cp == "grok":
            provider = "Grok"
        elif cp == "openai":
            provider = "OpenAI"
        elif CONFIG.get("anthropic_key"):
            provider = "Claude"
        else:
            provider = "Ollama/demo"
        model = CONFIG.get("xai_model") if CONFIG.get("xai_key") else CONFIG.get("ollama_model")
        if cp == "openai" and str(model).startswith("grok"):
            model = "gpt-4o"
        self.emit({
            "type": "brain_ready",
            "msg": f"ASTRA Brain online. Primary LLM: {provider}",
            "provider": provider,
            "model": model,
            "has_xai": bool(CONFIG.get("xai_key")),
            "cloud_provider": cp,
        })

    def handle_input(self, data: dict):
        msg_type = data.get("type", "")

        if msg_type == "chat":
            prompt = data.get("text", "")
            mode = data.get("mode", "default")
            self.memory.add_context("user", prompt)
            ctx = self.memory.get_context_str()
            full_prompt = f"Context:\n{ctx}\n\nCurrent request: {prompt}"
            response = self.nlp.route(full_prompt, mode)
            self.memory.add_context("astra", response)
            self.emit({"type": "chat_response", "text": response, "provider": "grok" if mode != "local" else "ollama"})

        elif msg_type == "set_config":
            cfg = data.get("config", {})
            # map UI fields
            if "xai_key" in cfg:
                CONFIG["xai_key"] = cfg["xai_key"] or CONFIG["xai_key"]
            if "xai_model" in cfg:
                CONFIG["xai_model"] = cfg["xai_model"]
            if "anthropic_key" in cfg:
                CONFIG["anthropic_key"] = cfg["anthropic_key"]
            CONFIG.update({k: v for k, v in cfg.items() if k in CONFIG or k in ("xai_key", "xai_model", "anthropic_key")})
            self.emit({"type": "config_updated", "has_xai": bool(CONFIG.get("xai_key"))})

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
    brain = ASTRABrain()
    brain.run()
