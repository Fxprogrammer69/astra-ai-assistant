"""
ASTRA agent loop: Grok tool-calling when available, else local demo tools.
Emits streaming deltas + tool_call events.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Callable, Optional

from tools import TOOL_DEFS, demo_agent, run_tool


def _post_json(url: str, headers: dict, payload: dict, timeout: int = 90) -> dict:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _stream_chat(url: str, headers: dict, payload: dict, on_delta: Callable[[str], None], timeout: int = 120) -> str:
    """SSE-ish OpenAI stream; returns full text."""
    payload = {**payload, "stream": True}
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    full = []
    with urllib.request.urlopen(req, timeout=timeout) as r:
        while True:
            line = r.readline()
            if not line:
                break
            line = line.decode("utf-8", errors="replace").strip()
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
                delta = chunk["choices"][0].get("delta") or {}
                t = delta.get("content") or ""
                if t:
                    full.append(t)
                    on_delta(t)
            except Exception:
                continue
    return "".join(full)


def run_agent_chat(
    *,
    prompt: str,
    system: str,
    config: dict,
    context: str = "",
    mode: str = "default",
    emit: Optional[Callable[[dict], None]] = None,
    use_tools: bool = True,
    stream: bool = True,
) -> str:
    """
    High-level agent entry. Prefer cloud tool loop; fall back to local tools / plain chat.
    """
    def _emit(ev: dict):
        if emit:
            emit(ev)

    key = config.get("xai_key") or ""
    base = (config.get("xai_base") or "https://api.x.ai/v1").rstrip("/")
    model = config.get("xai_model") or "grok-4.5"
    if config.get("cloud_provider") == "openai" and str(model).startswith("grok"):
        model = "gpt-4o"

    user_content = prompt
    if context:
        user_content = f"Context:\n{context}\n\nCurrent request: {prompt}"

    # Explicit local-tools mode, or no API key
    force_local_tools = mode in ("tools", "local") or not key
    if force_local_tools and use_tools and mode != "chat_only":
        if mode == "tools" or not key or any(
            w in prompt.lower()
            for w in ("list", "file", "desktop", "git", "run ", "system", "agent", "tool", "mission")
        ):
            text = demo_agent(prompt, emit=_emit)
            if not key:
                text = (
                    "_Cloud LLM offline (add xAI credits at console.x.ai). Using **local tools**._\n\n"
                    + text
                )
            if stream:
                for i in range(0, len(text), 48):
                    _emit({"type": "chat_delta", "text": text[i : i + 48]})
            return text

    if not key:
        text = (
            "Cloud LLM offline (no key or no credits). "
            "Try **Missions**, or chat mode **Local tools only** — e.g. “list desktop files”."
        )
        if stream:
            for i in range(0, len(text), 48):
                _emit({"type": "chat_delta", "text": text[i : i + 48]})
        return text

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
    }
    url = f"{base}/chat/completions"
    messages = [
        {"role": "system", "content": system + "\nYou may call tools when helpful. Be concise."},
        {"role": "user", "content": user_content},
    ]

    # Try tool-calling agent loop (max 4 rounds)
    if use_tools and mode != "chat_only":
        try:
            for _round in range(4):
                payload = {
                    "model": model,
                    "messages": messages,
                    "tools": TOOL_DEFS,
                    "tool_choice": "auto",
                    "temperature": 0.5,
                    "max_tokens": 1200,
                }
                data = _post_json(url, headers, payload, timeout=90)
                msg = (data.get("choices") or [{}])[0].get("message") or {}
                tool_calls = msg.get("tool_calls") or []
                if not tool_calls:
                    text = msg.get("content") or ""
                    if stream and text:
                        for i in range(0, len(text), 40):
                            _emit({"type": "chat_delta", "text": text[i : i + 40]})
                    return text or "[Empty model response]"

                messages.append(msg)
                for tc in tool_calls:
                    fn = tc.get("function") or {}
                    name = fn.get("name") or ""
                    raw_args = fn.get("arguments") or "{}"
                    try:
                        args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
                    except Exception:
                        args = {}
                    _emit({"type": "tool_call", "name": name, "args": args, "status": "running"})
                    result = run_tool(name, args)
                    _emit({
                        "type": "tool_result",
                        "name": name,
                        "ok": result.get("ok"),
                        "preview": json.dumps(result)[:400],
                    })
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id") or name,
                        "content": json.dumps(result),
                    })
            return "Agent hit tool-call limit. Summarize with what you have."
        except urllib.error.HTTPError as e:
            err = e.read().decode(errors="replace")[:300]
            _emit({"type": "warn", "msg": f"Tool-calling failed ({e.code}): {err} — falling back to plain chat/tools"})
            # credits / unsupported tools → local tools if action-y
            if any(w in prompt.lower() for w in ("list", "file", "desktop", "git", "system", "agent")):
                text = demo_agent(prompt, emit=_emit)
                if stream:
                    for i in range(0, len(text), 48):
                        _emit({"type": "chat_delta", "text": text[i : i + 48]})
                return text
        except Exception as e:
            _emit({"type": "warn", "msg": f"Agent loop error: {e}"})

    # Plain streaming chat
    try:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 1024,
        }
        if stream:
            text = _stream_chat(url, headers, payload, lambda t: _emit({"type": "chat_delta", "text": t}))
            return text or "[Empty stream]"
        data = _post_json(url, headers, payload)
        text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        if stream and text:
            for i in range(0, len(text), 40):
                _emit({"type": "chat_delta", "text": text[i : i + 40]})
        return text
    except urllib.error.HTTPError as e:
        err = e.read().decode(errors="replace")[:400]
        # Offline tools fallback
        text = (
            f"Cloud LLM error HTTP {e.code}: {err}\n\n"
            "Falling back to **local agent tools**:\n\n"
            + demo_agent(prompt, emit=_emit)
        )
        if stream:
            for i in range(0, len(text), 48):
                _emit({"type": "chat_delta", "text": text[i : i + 48]})
        return text
    except Exception as e:
        text = f"Chat failed: {e}\n\n" + demo_agent(prompt, emit=_emit)
        if stream:
            for i in range(0, len(text), 48):
                _emit({"type": "chat_delta", "text": text[i : i + 48]})
        return text
