#!/usr/bin/env python3
"""
ASTRA Brain Server
Handles: NLP routing, Whisper STT, MediaPipe CV + Gestures, Ollama local LLM
Communicates with Electron via stdin/stdout JSON + WebSocket on port 9001
"""

import sys
import json
import threading
import time
import base64
import os
from datetime import datetime

# ── WebSocket server ──────────────────────────────────────────────────────────
import asyncio
import websockets

WS_PORT = 9002  # Brain → Renderer events

# ── Lazy imports (graceful degradation if not installed) ──────────────────────
def try_import(name):
    try:
        return __import__(name)
    except ImportError:
        print(json.dumps({"type":"warn","msg":f"Module '{name}' not installed. Run setup.py."}), flush=True)
        return None

# ── Config ────────────────────────────────────────────────────────────────────
CONFIG = {
    "anthropic_key": os.environ.get("ANTHROPIC_API_KEY", ""),
    "ollama_url": "http://localhost:11434",
    "ollama_model": "llama3.1:8b",
    "whisper_model": "tiny",          # tiny | base | small | medium
    "vad_threshold": 0.5,
    "screenshot_interval": 10,        # seconds between screen reads
    "gesture_confidence": 0.75,
}

# ── NLP Router ────────────────────────────────────────────────────────────────
class NLPRouter:
    def __init__(self):
        self.anthropic = None
        self._init_anthropic()

    def _init_anthropic(self):
        try:
            import anthropic
            if CONFIG["anthropic_key"]:
                self.anthropic = anthropic.Anthropic(api_key=CONFIG["anthropic_key"])
        except ImportError:
            pass

    def route(self, prompt: str, mode: str = "default", image_b64: str = None) -> str:
        """Route to Claude API or Ollama based on mode/connectivity."""
        if mode == "local" or not CONFIG["anthropic_key"]:
            return self._ollama(prompt)
        try:
            return self._claude(prompt, image_b64)
        except Exception as e:
            print(json.dumps({"type":"warn","msg":f"Claude API failed, falling back to Ollama: {e}"}), flush=True)
            return self._ollama(prompt)

    def _claude(self, prompt: str, image_b64: str = None) -> str:
        if not self.anthropic:
            return self._ollama(prompt)
        msgs = []
        if image_b64:
            msgs.append({"role":"user","content":[
                {"type":"image","source":{"type":"base64","media_type":"image/png","data":image_b64}},
                {"type":"text","text":prompt}
            ]})
        else:
            msgs.append({"role":"user","content":prompt})

        resp = self.anthropic.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=ASTRA_SYSTEM_PROMPT,
            messages=msgs
        )
        return resp.content[0].text

    def _ollama(self, prompt: str) -> str:
        try:
            import urllib.request
            payload = json.dumps({
                "model": CONFIG["ollama_model"],
                "prompt": f"{ASTRA_SYSTEM_PROMPT}\n\nUser: {prompt}\nASTRA:",
                "stream": False
            }).encode()
            req = urllib.request.Request(
                f"{CONFIG['ollama_url']}/api/generate",
                data=payload,
                headers={"Content-Type":"application/json"}
            )
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read())
                return data.get("response","No response from Ollama.")
        except Exception as e:
            return f"[Local model unavailable: {e}. Install Ollama and run: ollama pull {CONFIG['ollama_model']}]"

# ── Whisper STT ───────────────────────────────────────────────────────────────
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
                self.event_cb({"type":"speech_ready","msg":"Whisper loaded"})
            except Exception as e:
                self.event_cb({"type":"warn","msg":f"Whisper load failed: {e}"})

    def start_vad_loop(self):
        """Always-on VAD → Whisper transcription loop."""
        sd = try_import("sounddevice")
        np = try_import("numpy")
        if not sd or not np or not self.whisper_model:
            self.event_cb({"type":"warn","msg":"Speech engine unavailable. Install: pip install sounddevice numpy openai-whisper"})
            return

        import tempfile, wave
        SAMPLE_RATE = 16000
        CHUNK = 1024
        SILENCE_THRESH = 0.01
        MIN_SPEECH_SECS = 0.8
        BUFFER_SECS = 3

        self.running = True
        self.event_cb({"type":"speech_listening","msg":"VAD active — no wake word needed"})

        buffer = []
        speaking = False
        silence_count = 0

        def audio_cb(indata, frames, time_info, status):
            nonlocal speaking, silence_count, buffer
            chunk = indata[:, 0]
            rms = float(np.sqrt(np.mean(chunk**2)))
            if rms > SILENCE_THRESH:
                speaking = True
                silence_count = 0
                buffer.extend(chunk.tolist())
            elif speaking:
                silence_count += 1
                buffer.extend(chunk.tolist())
                if silence_count > (SAMPLE_RATE / CHUNK) * 1.2:
                    # End of utterance — transcribe
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
                self.event_cb({"type":"speech_transcript","text":text})
        except Exception as e:
            self.event_cb({"type":"warn","msg":f"Transcription error: {e}"})

    def stop(self):
        self.running = False

# ── Computer Vision + Gestures ────────────────────────────────────────────────
class VisionEngine:
    """
    Handles:
      1. Screen awareness  — periodic screenshot → Claude Vision
      2. Webcam presence   — face detection, attention tracking
      3. Gesture control   — hand landmark gestures via MediaPipe
    """
    GESTURES = {
        # (name, action_event)
        "FIST":        "gesture_focus_lock",
        "OPEN_HAND":   "gesture_mode_switch",
        "PEACE":       "gesture_deep_work",
        "THUMBS_UP":   "gesture_confirm",
        "POINTING_UP": "gesture_scroll_up",
        "POINTING_DOWN":"gesture_scroll_down",
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
        if mp:
            self.mp = mp
            self.mp_hands = mp.solutions.hands.Hands(
                static_image_mode=False,
                max_num_hands=1,
                min_detection_confidence=CONFIG["gesture_confidence"],
                min_tracking_confidence=0.5
            )
            self.mp_face = mp.solutions.face_detection.FaceDetection(
                model_selection=0,
                min_detection_confidence=0.6
            )
            self.event_cb({"type":"cv_ready","msg":"MediaPipe loaded — CV online"})

    def start_webcam_loop(self):
        cv2 = try_import("cv2")
        np = try_import("numpy")
        if not cv2 or not np or not self.mp:
            self.event_cb({"type":"warn","msg":"CV unavailable. Install: pip install mediapipe opencv-python"})
            return

        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            self.event_cb({"type":"warn","msg":"Webcam not found"})
            return

        self.running = True
        self.event_cb({"type":"webcam_active","msg":"Webcam online — presence + gesture detection active"})

        last_gesture = None
        gesture_hold = 0
        presence_state = False
        face_absence_count = 0

        while self.running:
            ret, frame = cap.read()
            if not ret:
                break

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            # ── Presence detection ──
            face_results = self.mp_face.process(rgb)
            face_detected = bool(face_results.detections)
            if face_detected != presence_state:
                presence_state = face_detected
                self.event_cb({"type":"presence","present":presence_state})
                if not face_detected:
                    face_absence_count += 1
                    if face_absence_count >= 3:
                        self.event_cb({"type":"away_detected","msg":"User away — pausing focus timer"})

            # ── Gesture detection ──
            hand_results = self.mp_hands.process(rgb)
            if hand_results.multi_hand_landmarks:
                for hand_lm in hand_results.multi_hand_landmarks:
                    gesture = self._classify_gesture(hand_lm.landmark)
                    if gesture:
                        if gesture == last_gesture:
                            gesture_hold += 1
                            if gesture_hold == 5:  # held for ~5 frames
                                action = self.GESTURES.get(gesture)
                                if action:
                                    self.event_cb({"type":"gesture","gesture":gesture,"action":action})
                        else:
                            last_gesture = gesture
                            gesture_hold = 0
            else:
                last_gesture = None
                gesture_hold = 0

            time.sleep(0.033)  # ~30fps

        cap.release()

    def _classify_gesture(self, landmarks):
        """Classify hand gesture from MediaPipe landmarks."""
        # Landmark indices: 4=thumb_tip, 8=index_tip, 12=middle_tip, 16=ring_tip, 20=pinky_tip
        # Base joints:      3=thumb_ip,  6=index_pip, 10=mid_pip,    14=ring_pip, 18=pinky_pip
        lm = landmarks

        def tip_up(tip, pip):
            return lm[tip].y < lm[pip].y

        index_up  = tip_up(8, 6)
        middle_up = tip_up(12, 10)
        ring_up   = tip_up(16, 14)
        pinky_up  = tip_up(20, 18)
        thumb_up  = lm[4].y < lm[3].y

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
            # Check direction
            if lm[8].y < lm[5].y:
                return "POINTING_UP"
            else:
                return "POINTING_DOWN"
        return None

    def start_screen_loop(self, nlp_router):
        """Periodic screenshot → Claude Vision for proactive assistance."""
        pil = try_import("PIL")
        if not pil:
            self.event_cb({"type":"warn","msg":"Screen awareness unavailable. Install: pip install Pillow"})
            return

        import PIL.ImageGrab as ImageGrab
        import io

        self.event_cb({"type":"screen_watch_active","msg":"Screen awareness online"})

        while self.running:
            time.sleep(CONFIG["screenshot_interval"])
            try:
                screenshot = ImageGrab.grab()
                # Downscale for API efficiency
                screenshot = screenshot.resize((1280, 720))
                buf = io.BytesIO()
                screenshot.save(buf, format="PNG")
                b64 = base64.b64encode(buf.getvalue()).decode()
                response = nlp_router.route(
                    "Analyze this screenshot. What is the user working on? Any suggestions or alerts? Be brief — 1-2 sentences max.",
                    image_b64=b64
                )
                self.event_cb({"type":"screen_insight","text":response})
            except Exception as e:
                pass  # Silent fail for screen capture

    def stop(self):
        self.running = False

# ── Memory Layer ──────────────────────────────────────────────────────────────
class MemoryLayer:
    def __init__(self):
        self.db_path = os.path.join(os.path.dirname(__file__), "../../models/memory.json")
        self.data = self._load()

    def _load(self):
        try:
            with open(self.db_path) as f:
                return json.load(f)
        except:
            return {"goals":[],"tasks":[],"projects":[],"preferences":{},"context":[]}

    def save(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with open(self.db_path, "w") as f:
            json.dump(self.data, f, indent=2)

    def add_context(self, role, text):
        self.data["context"].append({"role":role,"text":text,"ts":datetime.now().isoformat()})
        if len(self.data["context"]) > 100:
            self.data["context"] = self.data["context"][-100:]
        self.save()

    def get_context_str(self, n=10):
        recent = self.data["context"][-n:]
        return "\n".join([f"{c['role'].upper()}: {c['text']}" for c in recent])

# ── ASTRA System Prompt ───────────────────────────────────────────────────────
ASTRA_SYSTEM_PROMPT = """You are ASTRA, an elite desktop AI operating system.
You are calm, sharp, concise, and execution-oriented.
You help with coding, research, trading, studying, and productivity.
Never be verbose. Always be actionable. Respond like a mission-critical AI assistant."""

# ── Main Brain ────────────────────────────────────────────────────────────────
class ASTRABrain:
    def __init__(self):
        self.nlp = NLPRouter()
        self.memory = MemoryLayer()
        self.speech = SpeechEngine(self.emit)
        self.vision = VisionEngine(self.emit)
        self._start_threads()

    def emit(self, event: dict):
        print(json.dumps(event), flush=True)

    def _start_threads(self):
        threading.Thread(target=self.speech.start_vad_loop, daemon=True).start()
        threading.Thread(target=self.vision.start_webcam_loop, daemon=True).start()
        threading.Thread(target=self.vision.start_screen_loop, args=(self.nlp,), daemon=True).start()
        self.emit({"type":"brain_ready","msg":"ASTRA Brain online. All subsystems starting."})

    def handle_input(self, data: dict):
        msg_type = data.get("type","")

        if msg_type == "chat":
            prompt = data.get("text","")
            mode = data.get("mode","default")
            self.memory.add_context("user", prompt)
            ctx = self.memory.get_context_str()
            full_prompt = f"Context:\n{ctx}\n\nCurrent request: {prompt}"
            response = self.nlp.route(full_prompt, mode)
            self.memory.add_context("astra", response)
            self.emit({"type":"chat_response","text":response})

        elif msg_type == "set_config":
            CONFIG.update(data.get("config",{}))
            self.emit({"type":"config_updated"})

        elif msg_type == "ping":
            self.emit({"type":"pong","ts":datetime.now().isoformat()})

    def run(self):
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                self.handle_input(data)
            except json.JSONDecodeError:
                self.emit({"type":"error","msg":f"Invalid JSON: {line}"})

if __name__ == "__main__":
    brain = ASTRABrain()
    brain.run()
