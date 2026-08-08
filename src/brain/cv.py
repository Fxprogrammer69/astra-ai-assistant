"""
ASTRA CV v2 — robust gestures, presence confidence, attention score,
screen-change detection, multi-camera open, MediaPipe + OpenCV fallbacks.
"""
from __future__ import annotations

import base64
import hashlib
import io
import time
from typing import Callable, Optional


def try_import(name: str):
    try:
        return __import__(name)
    except ImportError:
        return None


class VisionEngineV2:
    GESTURES = {
        "FIST": "gesture_focus_lock",
        "OPEN_HAND": "gesture_mode_switch",
        "PEACE": "gesture_deep_work",
        "THUMBS_UP": "gesture_confirm",
        "POINTING_UP": "gesture_scroll_up",
        "POINTING_DOWN": "gesture_scroll_down",
        "PINCH": "gesture_confirm",
        "OK": "gesture_confirm",
    }

    def __init__(self, event_cb: Callable[[dict], None], config: Optional[dict] = None):
        self.event_cb = event_cb
        self.config = config or {}
        self.running = False
        self.mp = None
        self.mp_hands = None
        self.mp_face = None
        self.mp_face_mesh = None
        self.backend = "none"
        self.face_cascade = None
        self._load()

    def _load(self):
        conf = float(self.config.get("gesture_confidence") or 0.7)
        mp = try_import("mediapipe")
        if mp and hasattr(mp, "solutions"):
            try:
                self.mp = mp
                self.mp_hands = mp.solutions.hands.Hands(
                    static_image_mode=False,
                    max_num_hands=2,
                    model_complexity=1,
                    min_detection_confidence=conf,
                    min_tracking_confidence=0.5,
                )
                self.mp_face = mp.solutions.face_detection.FaceDetection(
                    model_selection=0, min_detection_confidence=0.55
                )
                try:
                    self.mp_face_mesh = mp.solutions.face_mesh.FaceMesh(
                        static_image_mode=False,
                        max_num_faces=1,
                        refine_landmarks=True,
                        min_detection_confidence=0.5,
                        min_tracking_confidence=0.5,
                    )
                except Exception:
                    self.mp_face_mesh = None
                self.backend = "mediapipe"
                self.event_cb({"type": "cv_ready", "msg": "CV v2 MediaPipe online", "backend": "mediapipe"})
                return
            except Exception as e:
                self.event_cb({"type": "warn", "msg": f"MediaPipe failed, trying OpenCV fallback: {e}"})

        cv2 = try_import("cv2")
        if cv2:
            try:
                # Haar cascade ships with OpenCV
                path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
                self.face_cascade = cv2.CascadeClassifier(path)
                self.backend = "opencv"
                self.event_cb({"type": "cv_ready", "msg": "CV v2 OpenCV face fallback online", "backend": "opencv"})
                return
            except Exception as e:
                self.event_cb({"type": "warn", "msg": f"OpenCV fallback failed: {e}"})

        self.event_cb({"type": "warn", "msg": "CV unavailable. pip install mediapipe opencv-python"})

    def _open_camera(self, cv2):
        for idx in (0, 1, 2):
            cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW) if hasattr(cv2, "CAP_DSHOW") else cv2.VideoCapture(idx)
            if cap is not None and cap.isOpened():
                # warm frame
                ok, _ = cap.read()
                if ok:
                    return cap, idx
                cap.release()
        return None, -1

    def start_webcam_loop(self):
        cv2 = try_import("cv2")
        np = try_import("numpy")
        if not cv2 or not np or self.backend == "none":
            self.event_cb({"type": "warn", "msg": "CV unavailable. Install: pip install mediapipe opencv-python numpy"})
            return

        cap, cam_idx = self._open_camera(cv2)
        if not cap:
            self.event_cb({"type": "warn", "msg": "Webcam not found (tried indices 0-2)"})
            return

        self.running = True
        self.event_cb({
            "type": "webcam_active",
            "msg": f"Webcam online (index {cam_idx}) — presence + gestures",
            "camera": cam_idx,
            "backend": self.backend,
        })

        last_gesture = None
        gesture_hold = 0
        gesture_cooldown = 0
        presence_state = False
        away_frames = 0
        present_frames = 0
        hold_need = 6  # ~0.2s at 30fps — more stable
        attention_ema = 0.5
        last_attention_emit = 0.0

        while self.running:
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.05)
                continue

            # Downscale for speed
            h, w = frame.shape[:2]
            scale = 640 / max(w, 1)
            if scale < 1:
                frame_s = cv2.resize(frame, (int(w * scale), int(h * scale)))
            else:
                frame_s = frame
            rgb = cv2.cvtColor(frame_s, cv2.COLOR_BGR2RGB)

            face_detected = False
            face_conf = 0.0
            attention = attention_ema

            if self.backend == "mediapipe" and self.mp_face:
                face_results = self.mp_face.process(rgb)
                if face_results.detections:
                    face_detected = True
                    face_conf = float(face_results.detections[0].score[0])
                    # Attention proxy: face size / centeredness
                    bb = face_results.detections[0].location_data.relative_bounding_box
                    cx = bb.xmin + bb.width / 2
                    cy = bb.ymin + bb.height / 2
                    center_score = 1.0 - min(1.0, ((cx - 0.5) ** 2 + (cy - 0.5) ** 2) ** 0.5 * 2)
                    size_score = min(1.0, bb.width * 3.5)
                    attention = 0.55 * center_score + 0.45 * size_score
            elif self.backend == "opencv" and self.face_cascade is not None:
                gray = cv2.cvtColor(frame_s, cv2.COLOR_BGR2GRAY)
                faces = self.face_cascade.detectMultiScale(gray, 1.15, 5, minSize=(48, 48))
                face_detected = len(faces) > 0
                if face_detected:
                    face_conf = 0.7
                    x, y, fw, fh = faces[0]
                    cx = (x + fw / 2) / frame_s.shape[1]
                    cy = (y + fh / 2) / frame_s.shape[0]
                    center_score = 1.0 - min(1.0, ((cx - 0.5) ** 2 + (cy - 0.5) ** 2) ** 0.5 * 2)
                    size_score = min(1.0, (fw / frame_s.shape[1]) * 3.0)
                    attention = 0.55 * center_score + 0.45 * size_score

            attention_ema = 0.85 * attention_ema + 0.15 * attention

            # Debounced presence
            if face_detected:
                present_frames += 1
                away_frames = 0
            else:
                away_frames += 1
                present_frames = 0

            if not presence_state and present_frames >= 4:
                presence_state = True
                self.event_cb({
                    "type": "presence",
                    "present": True,
                    "confidence": round(face_conf, 3),
                    "attention": round(attention_ema, 3),
                })
            elif presence_state and away_frames >= 12:
                presence_state = False
                self.event_cb({"type": "presence", "present": False, "confidence": 0.0, "attention": 0.0})
                self.event_cb({"type": "away_detected", "msg": "User away — pausing focus timer"})

            # Periodic attention telemetry (~1Hz)
            now = time.time()
            if presence_state and (now - last_attention_emit) >= 1.0:
                last_attention_emit = now
                self.event_cb({
                    "type": "attention",
                    "score": round(attention_ema, 3),
                    "present": True,
                })

            # Gestures (MediaPipe only)
            if self.backend == "mediapipe" and self.mp_hands:
                if gesture_cooldown > 0:
                    gesture_cooldown -= 1
                hand_results = self.mp_hands.process(rgb)
                if hand_results.multi_hand_landmarks:
                    for hand_lm in hand_results.multi_hand_landmarks:
                        gesture = self._classify_gesture(hand_lm.landmark)
                        if gesture:
                            if gesture == last_gesture:
                                gesture_hold += 1
                                if gesture_hold == hold_need and gesture_cooldown == 0:
                                    action = self.GESTURES.get(gesture)
                                    if action:
                                        self.event_cb({
                                            "type": "gesture",
                                            "gesture": gesture,
                                            "action": action,
                                            "confidence": 0.85,
                                        })
                                        gesture_cooldown = 18  # ~0.6s debounce
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

        def dist(a, b):
            return ((lm[a].x - lm[b].x) ** 2 + (lm[a].y - lm[b].y) ** 2) ** 0.5

        index_up = tip_up(8, 6)
        middle_up = tip_up(12, 10)
        ring_up = tip_up(16, 14)
        pinky_up = tip_up(20, 18)
        thumb_up = lm[4].y < lm[3].y
        fingers_up = sum([index_up, middle_up, ring_up, pinky_up])

        # Pinch: thumb tip near index tip
        if dist(4, 8) < 0.05 and not middle_up:
            return "PINCH"
        # OK sign: thumb-index ring, other fingers up-ish
        if dist(4, 8) < 0.06 and middle_up and ring_up:
            return "OK"
        if fingers_up == 0 and not thumb_up:
            return "FIST"
        if fingers_up == 4:
            return "OPEN_HAND"
        if index_up and middle_up and not ring_up and not pinky_up:
            return "PEACE"
        if thumb_up and not index_up and fingers_up == 0:
            return "THUMBS_UP"
        if index_up and not middle_up and not ring_up and not pinky_up:
            return "POINTING_UP" if lm[8].y < lm[5].y else "POINTING_DOWN"
        return None

    def start_screen_loop(self, nlp_complete: Callable):
        """Screen awareness with change detection (skip LLM if static)."""
        pil = try_import("PIL")
        if not pil:
            self.event_cb({"type": "warn", "msg": "Screen awareness unavailable. pip install Pillow"})
            return
        import PIL.ImageGrab as ImageGrab

        interval = int(self.config.get("screenshot_interval") or 12)
        self.event_cb({"type": "screen_watch_active", "msg": "Screen awareness v2 online (change-detect)"})
        last_hash = None
        stable = 0

        while self.running:
            time.sleep(max(5, interval))
            try:
                screenshot = ImageGrab.grab()
                screenshot = screenshot.resize((960, 540))
                # Hash downscaled grayscale-ish bytes for change detection
                raw = screenshot.tobytes()
                h = hashlib.md5(raw[::50]).hexdigest()
                if h == last_hash:
                    stable += 1
                    if stable < 3:
                        continue  # no change
                    # still emit occasional heartbeat insight skip
                    continue
                last_hash = h
                stable = 0
                buf = io.BytesIO()
                screenshot.save(buf, format="PNG", optimize=True)
                b64 = base64.b64encode(buf.getvalue()).decode()
                self.event_cb({"type": "screen_change", "msg": "Screen content changed"})
                response = nlp_complete(
                    "Analyze this screenshot. What is the user working on? "
                    "Any blockers or suggestions? 1-2 sentences max.",
                    image_b64=b64,
                )
                if response:
                    self.event_cb({"type": "screen_insight", "text": response})
            except Exception as e:
                self.event_cb({"type": "warn", "msg": f"Screen loop: {e}"})

    def stop(self):
        self.running = False
