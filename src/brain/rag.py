"""
ASTRA RAG pipeline — pure-Python vector memory (no heavy native deps).
Stores every conversation turn, retrieves relevant past context on each query.
Supports multi-source imports (ChatGPT, Claude, Cursor, manual).
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


ROOT = Path(__file__).resolve().parent.parent.parent
RAG_DIR = ROOT / "models" / "rag"
CONV_PATH = RAG_DIR / "conversations.jsonl"
INDEX_PATH = RAG_DIR / "index.json"
PREFS_PATH = RAG_DIR / "preferences.json"
FACTS_PATH = RAG_DIR / "facts.json"
TRAIN_PATH = ROOT / "models" / "training" / "sft_pairs.jsonl"


def _tok(text: str) -> List[str]:
    t = (text or "").lower()
    t = re.sub(r"[^a-z0-9_\s\-/.:]", " ", t)
    parts = [p for p in t.split() if len(p) > 1]
    # also char 3-grams for short phrases
    joined = re.sub(r"\s+", "", t)[:400]
    grams = [joined[i : i + 3] for i in range(max(0, len(joined) - 2))]
    return parts + grams[:80]


def _embed(text: str, dim: int = 384) -> List[float]:
    """Deterministic bag-of-tokens hashed embedding (fast, offline)."""
    vec = [0.0] * dim
    toks = _tok(text)
    if not toks:
        return vec
    for tok in toks:
        h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
        idx = h % dim
        sign = 1.0 if (h >> 8) & 1 else -1.0
        # tf weight
        vec[idx] += sign
    # L2 normalize
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _cos(a: List[float], b: List[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


class RAGEngine:
    def __init__(self, emit=None):
        self.emit = emit or (lambda _e: None)
        RAG_DIR.mkdir(parents=True, exist_ok=True)
        (ROOT / "models" / "training").mkdir(parents=True, exist_ok=True)
        self.index: List[Dict[str, Any]] = []
        self.prefs: Dict[str, Any] = {"style": [], "likes": [], "dislikes": [], "user_name": "", "notes": []}
        self.facts: List[Dict[str, Any]] = []
        self._load()

    def _load(self):
        if INDEX_PATH.exists():
            try:
                self.index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
            except Exception:
                self.index = []
        if PREFS_PATH.exists():
            try:
                self.prefs = {**self.prefs, **json.loads(PREFS_PATH.read_text(encoding="utf-8"))}
            except Exception:
                pass
        if FACTS_PATH.exists():
            try:
                self.facts = json.loads(FACTS_PATH.read_text(encoding="utf-8"))
            except Exception:
                self.facts = []

    def _save_index(self):
        # keep index bounded
        if len(self.index) > 8000:
            self.index = self.index[-8000:]
        INDEX_PATH.write_text(json.dumps(self.index), encoding="utf-8")

    def _save_prefs(self):
        PREFS_PATH.write_text(json.dumps(self.prefs, indent=2), encoding="utf-8")

    def _save_facts(self):
        if len(self.facts) > 500:
            self.facts = self.facts[-500:]
        FACTS_PATH.write_text(json.dumps(self.facts, indent=2), encoding="utf-8")

    def add_turn(
        self,
        role: str,
        text: str,
        *,
        source: str = "astra",
        session: str = "default",
        meta: Optional[dict] = None,
    ) -> str:
        text = (text or "").strip()
        if not text:
            return ""
        rid = uuid.uuid4().hex[:12]
        rec = {
            "id": rid,
            "role": role,
            "text": text[:4000],
            "source": source,
            "session": session,
            "ts": datetime.now().isoformat(),
            "meta": meta or {},
        }
        with CONV_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

        emb = _embed(f"{role}: {text}")
        self.index.append({
            "id": rid,
            "role": role,
            "text": text[:800],
            "source": source,
            "session": session,
            "ts": rec["ts"],
            "emb": emb,
        })
        # persist occasionally (every 5 adds) for speed
        if len(self.index) % 5 == 0:
            self._save_index()
        return rid

    def flush(self):
        self._save_index()
        self._save_prefs()
        self._save_facts()

    def retrieve(self, query: str, k: int = 5, min_score: float = 0.08) -> List[Dict[str, Any]]:
        if not query or not self.index:
            return []
        q = _embed(query)
        scored: List[Tuple[float, Dict[str, Any]]] = []
        for item in self.index[-4000:]:
            emb = item.get("emb")
            if not emb:
                continue
            s = _cos(q, emb)
            if s >= min_score:
                scored.append((s, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        out = []
        seen = set()
        for s, item in scored:
            key = item.get("text", "")[:120]
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "score": round(s, 4),
                "role": item.get("role"),
                "text": item.get("text"),
                "source": item.get("source"),
                "ts": item.get("ts"),
                "id": item.get("id"),
            })
            if len(out) >= k:
                break
        return out

    def build_context_block(self, query: str, k: int = 4) -> str:
        hits = self.retrieve(query, k=k)
        facts = self.facts[-12:]
        prefs = self.prefs
        parts = []
        if prefs.get("user_name") or prefs.get("likes") or prefs.get("style") or prefs.get("notes"):
            pbits = []
            if prefs.get("user_name"):
                pbits.append(f"User: {prefs['user_name']}")
            if prefs.get("style"):
                pbits.append("Style: " + "; ".join(prefs["style"][-6:]))
            if prefs.get("likes"):
                pbits.append("Likes: " + "; ".join(prefs["likes"][-8:]))
            if prefs.get("dislikes"):
                pbits.append("Avoid: " + "; ".join(prefs["dislikes"][-6:]))
            if prefs.get("notes"):
                pbits.append("Notes: " + "; ".join(prefs["notes"][-6:]))
            parts.append("USER PROFILE:\n" + "\n".join(pbits))
        if facts:
            parts.append("KNOWN FACTS:\n" + "\n".join(f"- {f.get('text','')}" for f in facts))
        if hits:
            lines = []
            for h in hits:
                src = h.get("source") or "astra"
                role = h.get("role") or "?"
                lines.append(f"[{src}/{role} · {h.get('score')}] {h.get('text')}")
            parts.append("RELEVANT MEMORY (RAG):\n" + "\n".join(lines))
        return "\n\n".join(parts)

    def add_fact(self, text: str, source: str = "learn"):
        text = (text or "").strip()
        if not text or len(text) < 4:
            return
        # dedupe
        low = text.lower()
        if any((f.get("text") or "").lower() == low for f in self.facts):
            return
        self.facts.append({"text": text[:300], "source": source, "ts": datetime.now().isoformat()})
        self._save_facts()
        self.add_turn("system", f"FACT: {text}", source=source)

    def learn_from_exchange(self, user: str, assistant: str, source: str = "astra"):
        """Lightweight continual learning: extract prefs + store SFT pair."""
        u = (user or "").strip()
        a = (assistant or "").strip()
        if not u or not a:
            return

        # Training pair for future fine-tune export
        try:
            with TRAIN_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "messages": [
                        {"role": "user", "content": u[:2000]},
                        {"role": "assistant", "content": a[:3000]},
                    ],
                    "source": source,
                    "ts": datetime.now().isoformat(),
                }, ensure_ascii=False) + "\n")
        except Exception:
            pass

        # Heuristic preference mining
        ul = u.lower()
        if re.search(r"\b(my name is|call me|i am|i'm)\b", ul):
            m = re.search(r"(?:my name is|call me|i am|i'm)\s+([A-Za-z][\w\s-]{1,40})", u, re.I)
            if m:
                self.prefs["user_name"] = m.group(1).strip()[:40]
        if re.search(r"\b(i (prefer|like|love|want|need)|always|never)\b", ul):
            self.prefs.setdefault("likes", []).append(u[:160])
            self.prefs["likes"] = self.prefs["likes"][-30:]
        if re.search(r"\b(don't|do not|hate|avoid|stop|too slow|never)\b", ul):
            self.prefs.setdefault("dislikes", []).append(u[:160])
            self.prefs["dislikes"] = self.prefs["dislikes"][-30:]
        if re.search(r"\b(be (more )?(brief|concise|short|detailed|formal|casual)|speak like)\b", ul):
            self.prefs.setdefault("style", []).append(u[:160])
            self.prefs["style"] = self.prefs["style"][-20:]
        if re.search(r"\b(remember that|note that|don't forget|always remember)\b", ul):
            self.add_fact(u[:250], source=source)

        # If user complains about speed — store style preference
        if "slow" in ul or "faster" in ul:
            self.prefs.setdefault("style", []).append("Prefer fast, short replies")
            self.prefs["style"] = self.prefs["style"][-20:]

        self._save_prefs()

    def import_messages(self, messages: List[Dict[str, Any]], source: str = "import") -> int:
        """Import list of {role, content|text} from other AIs."""
        n = 0
        last_user = ""
        for m in messages:
            role = (m.get("role") or "user").lower()
            if role in ("human", "customer"):
                role = "user"
            if role in ("bot", "assistant", "model", "ai", "gpt", "claude"):
                role = "assistant"
            text = m.get("content") or m.get("text") or m.get("message") or ""
            if isinstance(text, list):
                # OpenAI multimodal content blocks
                text = " ".join(
                    (b.get("text") if isinstance(b, dict) else str(b)) for b in text
                )
            text = str(text).strip()
            if not text:
                continue
            self.add_turn(role, text, source=source)
            if role == "user":
                last_user = text
            elif role == "assistant" and last_user:
                try:
                    self.learn_from_exchange(last_user, text, source=source)
                except Exception:
                    pass
                last_user = ""
            n += 1
        self.flush()
        self.emit({"type": "rag_import", "count": n, "source": source})
        return n

    def import_json_file(self, path: str, source: str = "import") -> int:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(path)
        raw = p.read_text(encoding="utf-8", errors="replace")
        data = json.loads(raw)

        # ChatGPT export: array of conversations with mapping
        if isinstance(data, list) and data and isinstance(data[0], dict) and "mapping" in data[0]:
            msgs = []
            for conv in data:
                mapping = conv.get("mapping") or {}
                for node in mapping.values():
                    msg = (node or {}).get("message") or {}
                    role = ((msg.get("author") or {}).get("role")) or ""
                    content = msg.get("content") or {}
                    parts = content.get("parts") if isinstance(content, dict) else None
                    if parts:
                        text = "\n".join(str(x) for x in parts if x)
                        if text.strip():
                            msgs.append({"role": role or "user", "text": text})
            return self.import_messages(msgs, source=source or "chatgpt")

        # Claude / generic: {messages: [...]} or list of messages
        if isinstance(data, dict) and "messages" in data:
            return self.import_messages(data["messages"], source=source)
        if isinstance(data, list):
            return self.import_messages(data, source=source)
        raise ValueError("Unrecognized conversation export format")

    def import_text_blob(self, text: str, source: str = "paste") -> int:
        """Import pasted multi-line chats: 'User: ...' / 'Assistant: ...'"""
        msgs = []
        cur_role, cur_buf = None, []
        for line in (text or "").splitlines():
            m = re.match(r"^\s*(user|human|me|you|assistant|astra|ai|claude|gpt|grok)\s*[:\-]\s*(.*)$", line, re.I)
            if m:
                if cur_role and cur_buf:
                    msgs.append({"role": cur_role, "text": "\n".join(cur_buf).strip()})
                role = m.group(1).lower()
                if role in ("me", "you", "human"):
                    role = "user"
                if role in ("ai", "astra", "claude", "gpt", "grok"):
                    role = "assistant"
                cur_role = role
                cur_buf = [m.group(2)]
            else:
                if cur_role:
                    cur_buf.append(line)
        if cur_role and cur_buf:
            msgs.append({"role": cur_role, "text": "\n".join(cur_buf).strip()})
        return self.import_messages(msgs, source=source)

    def stats(self) -> Dict[str, Any]:
        conv_lines = 0
        if CONV_PATH.exists():
            with CONV_PATH.open(encoding="utf-8") as f:
                for _ in f:
                    conv_lines += 1
        train_lines = 0
        if TRAIN_PATH.exists():
            with TRAIN_PATH.open(encoding="utf-8") as f:
                for _ in f:
                    train_lines += 1
        sources: Dict[str, int] = {}
        for item in self.index[-2000:]:
            s = item.get("source") or "astra"
            sources[s] = sources.get(s, 0) + 1
        return {
            "index_size": len(self.index),
            "conversations": conv_lines,
            "training_pairs": train_lines,
            "facts": len(self.facts),
            "sources": sources,
            "prefs": {
                "user_name": self.prefs.get("user_name") or "",
                "likes": len(self.prefs.get("likes") or []),
                "style": len(self.prefs.get("style") or []),
            },
            "paths": {
                "conversations": str(CONV_PATH),
                "training": str(TRAIN_PATH),
                "index": str(INDEX_PATH),
            },
        }

    def system_addon(self) -> str:
        """Compact learned identity block for system prompt."""
        p = self.prefs
        bits = [
            "You are ASTRA — fast, concise, Jarvis-like. Prefer short replies unless asked for depth.",
            "Use retrieved memory when relevant. Never invent past facts.",
        ]
        if p.get("user_name"):
            bits.append(f"User's name: {p['user_name']}.")
        if p.get("style"):
            bits.append("Communication prefs: " + " | ".join(p["style"][-4:]))
        if p.get("likes"):
            bits.append("User likes: " + " | ".join(p["likes"][-4:]))
        if p.get("dislikes"):
            bits.append("User dislikes: " + " | ".join(p["dislikes"][-4:]))
        if self.facts:
            bits.append("Facts: " + " · ".join(f.get("text", "")[:80] for f in self.facts[-6:]))
        return "\n".join(bits)
