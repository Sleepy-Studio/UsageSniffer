"""Continue (continue.dev) parser: ~/.continue/sessions/<uuid>.json

Per-session JSON: {sessionId, title, workspaceDirectory, history[],
mode, chatModelTitle, usage?}. usage (when the model reports it):
{totalCost, promptTokens, completionTokens,
promptTokensDetails{cachedTokens, cacheWriteTokens}}.
Newer builds may carry per-assistant-message usage — picked up when present.
Index sessions.json carries no tokens and is only a fallback listing.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from ..models import SessionRecord


def _epoch(v) -> float:
    if not v:
        return 0.0
    try:
        if isinstance(v, (int, float)):
            return float(v / 1000) if v > 1e12 else float(v)
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _content_chars(content) -> int:
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        n = 0
        for p in content:
            if isinstance(p, dict):
                n += len(str(p.get("text", p.get("content", ""))))
            else:
                n += len(str(p))
        return n
    return len(str(content))


def parse_file(path: Path) -> SessionRecord:
    rec = SessionRecord(session_id=path.stem, agent="continue")
    try:
        o = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return rec
    if not isinstance(o, dict):
        return rec
    rec.project = str(o.get("workspaceDirectory", o.get("title", "")))
    rec.cwd = str(o.get("workspaceDirectory", ""))
    rec.model = str(o.get("chatModelTitle", o.get("model", "")))
    history = o.get("history", []) or []
    for item in history:
        msg = item.get("message", item) if isinstance(item, dict) else {}
        if not isinstance(msg, dict):
            continue
        role = msg.get("role", "")
        if role not in ("user", "assistant", "system", "tool"):
            continue
        rec.n_messages += 1
        chars = _content_chars(msg.get("content", ""))
        u = msg.get("usage", {}) or {}
        if role == "assistant":
            if u:
                pt = int(u.get("promptTokens", 0) or 0)
                ct = int(u.get("completionTokens", 0) or 0)
                det = u.get("promptTokensDetails", {}) or {}
                cached = int(det.get("cachedTokens", 0) or 0)
                cwr = int(det.get("cacheWriteTokens", 0) or 0)
                rec.input_tokens += pt
                rec.output_tokens += ct
                rec.cache_read += cached
                rec.cache_write += cwr
                rec.buckets["assistant_text"] += ct
                rec.buckets["context_cache"] += cached
                rec.buckets["context_write"] += cwr
                rec.buckets["system"] += max(0, pt - cached)
            else:
                rec.output_tokens += chars // 4
                rec.buckets["assistant_text"] += chars // 4
            for tc in msg.get("toolCalls", []) or []:
                name = str(tc.get("function", tc.get("name", "tool")))
                rec.tools[name] += 1
                rec.buckets["tools"] += chars // 8
            for ts in msg.get("toolCallStates", []) or []:
                name = str(ts.get("function", ts.get("name", "tool")))
                rec.tools[name] += 1
        elif role == "user":
            rec.buckets["user"] += chars // 4
        elif role == "tool":
            rec.buckets["tools"] += chars // 4
    u = o.get("usage", {}) or {}
    if u and not rec.input_tokens:
        pt = int(u.get("promptTokens", 0) or 0)
        ct = int(u.get("completionTokens", 0) or 0)
        det = u.get("promptTokensDetails", {}) or {}
        rec.input_tokens = pt
        rec.output_tokens = ct
        rec.cache_read = int(det.get("cachedTokens", 0) or 0)
        rec.cache_write = int(det.get("cacheWriteTokens", 0) or 0)
        rec.buckets["assistant_text"] += ct
        rec.buckets["context_cache"] += rec.cache_read
    if not rec.n_messages:
        rec.n_messages = len(history)
    return rec


def scan(root: Path | None = None) -> list[SessionRecord]:
    if root is None:
        base = os.environ.get("CONTINUE_GLOBAL_DIR", str(Path.home() / ".continue"))
        root = Path(base) / "sessions"
    out: list[SessionRecord] = []
    if not root.exists():
        return out
    for f in sorted(root.glob("*.json")):
        if f.name == "sessions.json":
            continue
        try:
            rec = parse_file(f)
            if rec.n_messages:
                out.append(rec)
        except Exception:
            continue
    return out
