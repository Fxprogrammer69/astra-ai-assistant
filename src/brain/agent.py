"""
ASTRA agent loop: local Ollama (fast) + cloud NVIDIA/Grok, tool-calling optional.
Emits streaming deltas + tool_call events.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Callable, Optional, Tuple

from tools import TOOL_DEFS, demo_agent, run_tool

# Cache Ollama health briefly so routing stays cheap
_ollama_cache: dict = {"ok": False, "ts": 0.0, "models": []}


def ollama_healthy(config: dict, ttl: float = 8.0) -> bool:
    now = time.time()
    if now - _ollama_cache["ts"] < ttl:
        return bool(_ollama_cache["ok"])
    url = (config.get("ollama_url") or "http://localhost:11434").rstrip("/")
    try:
        req = urllib.request.Request(f"{url}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=0.6) as r:
            data = json.loads(r.read().decode())
        models = [m.get("name") for m in (data.get("models") or []) if m.get("name")]
        _ollama_cache.update({"ok": True, "ts": now, "models": models})
        return True
    except Exception:
        _ollama_cache.update({"ok": False, "ts": now, "models": []})
        return False


def _pick_ollama_model(config: dict) -> str:
    preferred = (config.get("ollama_model") or "llama3.2:3b").strip()
    models = _ollama_cache.get("models") or []
    if not models:
        return preferred
    # exact or tag prefix match
    for m in models:
        if m == preferred or m.startswith(preferred.split(":")[0]):
            if preferred in m or m == preferred:
                return m if m == preferred else preferred
    if preferred in models:
        return preferred
    # Prefer small/fast locals
    for cand in ("llama3.2:3b", "llama3.2:1b", "phi3:mini", "qwen2.5:3b", "gemma2:2b", "llama3.1:8b"):
        for m in models:
            if m == cand or m.startswith(cand.split(":")[0] + ":"):
                if cand in m or m.startswith(cand):
                    return m if m == cand else (m if cand in models else m)
        if cand in models:
            return cand
    return models[0]


def _post_json(url: str, headers: dict, payload: dict, timeout: int = 90) -> dict:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _stream_chat(url: str, headers: dict, payload: dict, on_delta: Callable[[str], None], timeout: int = 90) -> str:
    """SSE-ish OpenAI stream; returns full text.
    Some providers (incl. NVIDIA NIM) stall after last token without [DONE].
    Use a per-read idle timeout and treat idle-after-content as success.
    """
    import socket

    payload = {**payload, "stream": True}
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    full = []
    idle_limit = 12  # seconds with no new bytes after first token
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            # Make socket reads fail after idle_limit once we have content
            try:
                r.fp.raw._sock.settimeout(idle_limit)  # type: ignore[attr-defined]
            except Exception:
                try:
                    r.fp.raw.settimeout(idle_limit)  # type: ignore[attr-defined]
                except Exception:
                    pass
            while True:
                try:
                    line = r.readline()
                except (socket.timeout, TimeoutError, OSError):
                    # Idle after tokens → treat as complete
                    if full:
                        break
                    raise
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
                    choice0 = (chunk.get("choices") or [{}])[0]
                    delta = choice0.get("delta") or {}
                    t = delta.get("content") or ""
                    if not t and choice0.get("finish_reason"):
                        break
                    if t:
                        full.append(t)
                        on_delta(t)
                except Exception:
                    continue
    except Exception:
        if full:
            return "".join(full)
        raise
    return "".join(full)


def _ollama_chat(
    *,
    system: str,
    user_content: str,
    config: dict,
    on_delta: Optional[Callable[[str], None]] = None,
    stream: bool = True,
    timeout: int = 30,
) -> Tuple[str, str]:
    """Local Ollama chat. Returns (text, model_name)."""
    base = (config.get("ollama_url") or "http://localhost:11434").rstrip("/")
    model = _pick_ollama_model(config)
    max_tokens = int(config.get("max_tokens") or 256)
    temperature = float(config.get("temperature") or 0.4)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ]
    # Prefer OpenAI-compatible endpoint when available
    payload = {
        "model": model,
        "messages": messages,
        "stream": bool(stream),
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }
    url = f"{base}/api/chat"
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    full = []
    with urllib.request.urlopen(req, timeout=timeout) as r:
        if stream:
            while True:
                line = r.readline()
                if not line:
                    break
                try:
                    chunk = json.loads(line.decode("utf-8", errors="replace"))
                except Exception:
                    continue
                msg = chunk.get("message") or {}
                t = msg.get("content") or ""
                if t:
                    full.append(t)
                    if on_delta:
                        on_delta(t)
                if chunk.get("done"):
                    break
        else:
            data = json.loads(r.read().decode())
            t = ((data.get("message") or {}).get("content")) or data.get("response") or ""
            if t:
                full.append(t)
                if on_delta:
                    # chunk for UI
                    step = 20
                    for i in range(0, len(t), step):
                        on_delta(t[i : i + step])
    return "".join(full), model


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
    High-level agent entry.
    Route: local Ollama (fast) → cloud NVIDIA/Grok → Claude → local tools.
    """
    def _emit(ev: dict):
        if emit:
            emit(ev)

    key = config.get("xai_key") or ""
    anthropic_key = config.get("anthropic_key") or ""
    base = (config.get("xai_base") or "https://api.x.ai/v1").rstrip("/")
    model = config.get("xai_model") or "grok-4.5"
    if config.get("cloud_provider") == "openai" and str(model).startswith("grok"):
        model = "gpt-4o"
    if config.get("cloud_provider") == "nvidia" and (
        str(model).startswith("grok") or not model
    ):
        model = config.get("xai_model") or "meta/llama-3.2-3b-instruct"

    # Speed knobs
    max_tokens = int(config.get("max_tokens") or 256)
    temperature = float(config.get("temperature") or 0.4)
    route = (config.get("route") or "auto").lower()  # auto | local | cloud
    # Cap context so prompts stay small/fast
    if context and len(context) > 2200:
        context = context[:600] + "\n…\n" + context[-1400:]

    # Context (if any) is folded into system — never into the user turn
    # (local models otherwise echo the memory block as the "answer")
    if context:
        system = (
            (system or "")
            + "\n\nUse this background only if relevant. Never quote or reprint it:\n"
            + context
        )
    user_content = prompt

    # ── Local-first fast path ────────────────────────────────────────────────
    prefer_local = (
        route in ("local", "auto", "ollama") or mode in ("local", "ollama")
    ) and mode not in ("grok", "claude", "nvidia")
    force_cloud = route in ("cloud", "nvidia", "grok") or mode in ("grok", "claude")
    force_local_only = route == "local" or mode in ("local", "ollama")
    if prefer_local and not force_cloud and mode not in ("tools", "agent"):
        if ollama_healthy(config):
            try:
                t0 = time.time()
                _emit({"type": "chat_start", "mode": "ollama", "model": _pick_ollama_model(config)})
                text, used_model = _ollama_chat(
                    system=system + "\nBe brief and fast.",
                    user_content=user_content,
                    config=config,
                    on_delta=(lambda t: _emit({"type": "chat_delta", "text": t})) if stream else None,
                    stream=stream,
                    timeout=25,
                )
                if text:
                    ms = int((time.time() - t0) * 1000)
                    config["_last_provider"] = "ollama"
                    config["_last_model"] = used_model
                    config["_last_ms"] = ms
                    _emit({"type": "chat_metrics", "ms": ms, "model": used_model, "provider": "ollama"})
                    return text
            except Exception as e:
                _emit({"type": "warn", "msg": f"Ollama failed ({e}) — trying cloud"})
                if force_local_only:
                    text = f"Ollama error: {e}"
                    if stream:
                        _emit({"type": "chat_delta", "text": text})
                    return text
        elif force_local_only:
            text = "Local Ollama offline. Run `ollama serve` and `ollama pull llama3.2:3b`."
            if stream:
                _emit({"type": "chat_delta", "text": text})
            return text

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

    # Prefer Grok/OpenAI-compatible; if no xAI key, try Claude Messages API
    if not key and anthropic_key and mode != "tools":
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=anthropic_key)
            _emit({"type": "chat_start", "mode": "claude"})
            resp = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1024,
                system=system,
                messages=[{"role": "user", "content": user_content}],
            )
            text = resp.content[0].text if resp.content else ""
            if stream and text:
                for i in range(0, len(text), 40):
                    _emit({"type": "chat_delta", "text": text[i : i + 40]})
            return text or "[Empty Claude response]"
        except Exception as e:
            _emit({"type": "warn", "msg": f"Claude failed: {e}"})
            # fall through to tools / offline messaging

    if not key and not anthropic_key:
        text = (
            "Cloud LLM offline (no key or no credits). "
            "Try **Missions**, or chat mode **Local tools only** — e.g. “list desktop files”."
        )
        if stream:
            for i in range(0, len(text), 48):
                _emit({"type": "chat_delta", "text": text[i : i + 48]})
        return text

    if not key and anthropic_key:
        # Claude already attempted above
        text = (
            f"Claude unavailable. Falling back to local tools.\n\n"
            + demo_agent(prompt, emit=_emit)
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
    provider = config.get("cloud_provider") or ""

    # Tools are slow — only when explicitly requested (tools/agent mode).
    want_tools = use_tools and mode in ("tools", "agent")

    # Try tool-calling agent loop (max 4 rounds)
    if want_tools:
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
            _emit({"type": "warn", "msg": f"Tool-calling failed ({e.code}): {err} — falling back to plain chat"})
            # reset messages so plain chat isn't polluted by tool state
            messages = [
                {"role": "system", "content": system + "\nBe concise and helpful."},
                {"role": "user", "content": user_content},
            ]
        except Exception as e:
            _emit({"type": "warn", "msg": f"Agent loop error: {e} — plain chat fallback"})
            messages = [
                {"role": "system", "content": system + "\nBe concise and helpful."},
                {"role": "user", "content": user_content},
            ]

    # Fast path: stream with idle timeout (first tokens ASAP). Fallback non-stream.
    try:
        t0 = __import__("time").time()
        _emit({"type": "chat_start", "mode": provider or "cloud", "model": model})
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        text = ""
        if stream:
            try:
                text = _stream_chat(
                    url, headers, payload,
                    lambda t: _emit({"type": "chat_delta", "text": t}),
                    timeout=45,
                )
            except Exception as se:
                _emit({"type": "warn", "msg": f"Stream failed ({se}); non-stream retry"})
        if not text:
            data = _post_json(url, headers, payload, timeout=45)
            text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            if stream and text:
                # chunk quickly for UI
                step = 24
                for i in range(0, len(text), step):
                    _emit({"type": "chat_delta", "text": text[i : i + step]})
        ms = int((__import__("time").time() - t0) * 1000)
        config["_last_provider"] = provider or "cloud"
        config["_last_model"] = model
        config["_last_ms"] = ms
        _emit({"type": "chat_metrics", "ms": ms, "model": model, "provider": provider})
        return text or "[Empty model response]"
    except urllib.error.HTTPError as e:
        err = e.read().decode(errors="replace")[:400]
        # Cloud failed → try Ollama, then Claude
        if ollama_healthy(config, ttl=2.0):
            try:
                _emit({"type": "warn", "msg": f"Cloud HTTP {e.code} — falling back to Ollama"})
                text, used_model = _ollama_chat(
                    system=system,
                    user_content=user_content,
                    config=config,
                    on_delta=(lambda t: _emit({"type": "chat_delta", "text": t})) if stream else None,
                    stream=stream,
                    timeout=30,
                )
                if text:
                    _emit({"type": "chat_metrics", "model": used_model, "provider": "ollama"})
                    return text
            except Exception as oe:
                _emit({"type": "warn", "msg": f"Ollama fallback failed: {oe}"})
        if anthropic_key:
            try:
                import anthropic
                client = anthropic.Anthropic(api_key=anthropic_key)
                _emit({"type": "warn", "msg": f"Cloud HTTP {e.code} — trying Claude"})
                resp = client.messages.create(
                    model=config.get("claude_model") or "claude-sonnet-4-20250514",
                    max_tokens=512,
                    system=system,
                    messages=[{"role": "user", "content": user_content}],
                )
                text = resp.content[0].text if resp.content else ""
                if stream and text:
                    for i in range(0, len(text), 40):
                        _emit({"type": "chat_delta", "text": text[i : i + 40]})
                return text or "[Empty Claude response]"
            except Exception as ce:
                _emit({"type": "warn", "msg": f"Claude also failed: {ce}"})
        text = (
            f"Cloud LLM error HTTP {e.code}: {err}\n\n"
            "Tip: start Ollama (`ollama serve`) or check NVIDIA key.\n\n"
            + demo_agent(prompt, emit=_emit)
        )
        if stream:
            for i in range(0, len(text), 48):
                _emit({"type": "chat_delta", "text": text[i : i + 48]})
        return text
    except Exception as e:
        # Last resort: Ollama then tools
        if ollama_healthy(config, ttl=2.0):
            try:
                text, used_model = _ollama_chat(
                    system=system,
                    user_content=user_content,
                    config=config,
                    on_delta=(lambda t: _emit({"type": "chat_delta", "text": t})) if stream else None,
                    stream=stream,
                    timeout=30,
                )
                if text:
                    _emit({"type": "chat_metrics", "model": used_model, "provider": "ollama"})
                    return text
            except Exception:
                pass
        text = f"Chat failed: {e}\n\n" + demo_agent(prompt, emit=_emit)
        if stream:
            for i in range(0, len(text), 48):
                _emit({"type": "chat_delta", "text": text[i : i + 48]})
        return text
