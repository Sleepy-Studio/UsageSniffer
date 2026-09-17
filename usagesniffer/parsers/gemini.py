"""Gemini CLI parser: ~/.gemini/tmp/<project>/chats/*.json

ConversationRecord format: array of records with
- {type: user, text}
- {type: gemini, model, thoughts, toolCalls, tokens: {input, output,
  cached, thoughts, tool, total}}
- {type: info|error|warning} status records (skipped).

Token ground truth per gemini message; no local cost field (priced externally).
Missing cached/thoughts treated as unknown (0) — ACP bug era caveat.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ..models import SessionRecord


def _to_epoch(v) -> float:
    if not v:
        return 0.0
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def parse_file(path: Path, project: str) -> SessionRecord:
    rec = SessionRecord(session_id=path.stem, agent="gemini", project=project)
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return rec
    records = data if isinstance(data, list) else data.get("records", data.get("messages", []))
    if not isinstance(records, list):
        return rec
    for r in records:
        if not isinstance(r, dict):
            continue
        t = r.get("type", "")
        if t == "user":
            rec.n_messages += 1
            txt = str(r.get("text", ""))
            rec.buckets["user"] += len(txt) // 4
            if not rec.started:
                rec.started = _to_epoch(r.get("timestamp", r.get("time", "")))
        elif t == "gemini":
            rec.n_messages += 1
            if not rec.model:
                rec.model = str(r.get("model", ""))
            toks = r.get("tokens", {}) or {}
            inp = int(toks.get("input", 0) or 0)
            out = int(toks.get("output", 0) or 0)
            cached = int(toks.get("cached", 0) or 0)
            thoughts = int(toks.get("thoughts", 0) or 0)
            toolt = int(toks.get("tool", 0) or 0)
            rec.input_tokens += inp
            rec.output_tokens += out
            rec.cache_read += cached
            rec.reasoning_tokens += thoughts
            rec.buckets["thinking"] += thoughts
            rec.buckets["context_cache"] += cached
            rec.buckets["assistant_text"] += max(0, out)
            rec.buckets["tools"] += toolt + max(0, inp - cached) // 3
            rec.buckets["system"] += max(0, inp - cached) - max(0, inp - cached) // 3
            for tc in r.get("toolCalls", []) or []:
                name = str(tc.get("name", tc.get("tool", "tool")))
                rec.tools[name] += 1
            if r.get("thoughts"):
                rec.buckets["thinking"] += len(str(r["thoughts"])) // 8
            if not rec.started:
                rec.started = _to_epoch(r.get("timestamp", r.get("time", "")))
    return rec


def scan(root: Path | None = None) -> list[SessionRecord]:
    root = root or (Path.home() / ".gemini" / "tmp")
    out: list[SessionRecord] = []
    if not root.exists():
        return out
    for chats in sorted(root.glob("*/chats")):
        project = chats.parent.name
        for f in sorted(chats.glob("*.json")):
            try:
                out.append(parse_file(f, project))
            except Exception:
                continue
    return out
