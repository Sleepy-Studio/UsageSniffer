"""Gemini CLI parser: ~/.gemini/tmp/<project_hash>/chats/

(GEMINI_CLI_HOME overrides ~/.gemini; the CLI appends .gemini to it.)

Three generations coexist:
- session-*.jsonl (current): first line is session metadata
  {sessionId, projectHash, startTime, lastUpdated, kind, directories},
  followed by message lines {id, timestamp, type, content, thoughts,
  tokens, model, toolCalls} and control lines ($set, $rewindTo).
  Subagent chats nest under chats/<parentSessionId>/*.jsonl.
- session-*.json (legacy): whole-session {sessionId, startTime,
  lastUpdated, messages: [...]} with the same message shape.
- bare array-of-records: [{type: user, text}, {type: gemini, model,
  thoughts, toolCalls, tokens: {input, output, cached, thoughts,
  tool, total}}, ...] — info/error/warning records skipped.

Message types: user -> user; gemini/model -> assistant. Content is a
string or an array of parts with `text`. Tokens per gemini message:
{input, output, cached, thoughts, tool, total} mapped from
promptTokenCount / candidatesTokenCount / cachedContentTokenCount /
thoughtsTokenCount / toolUsePromptTokenCount. No local cost field
(priced externally). Rewound-away ($rewindTo) turns keep their billed
tokens — spend is spend.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from ..models import SessionRecord


def _to_epoch(v) -> float:
    if not v:
        return 0.0
    try:
        if isinstance(v, (int, float)):
            return float(v / 1000) if v > 1e12 else float(v)
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, dict):
                parts.append(str(p.get("text", p.get("content", ""))))
            else:
                parts.append(str(p))
        return "".join(parts)
    if isinstance(content, dict):
        return str(content.get("text", content.get("content", "")))
    return str(content or "")


def _accumulate(rec: SessionRecord, msg: dict, session_start: float) -> None:
    """Fold one new-format message ({type, content, tokens, ...}) into rec."""
    if not isinstance(msg, dict):
        return
    t = str(msg.get("type", ""))
    ts = _to_epoch(msg.get("timestamp")) or session_start
    if t == "user":
        rec.n_messages += 1
        rec.buckets["user"] += len(_text_of(msg.get("content", ""))) // 4
        if not rec.started:
            rec.started = ts
    elif t in ("gemini", "model"):
        rec.n_messages += 1
        if not rec.model:
            rec.model = str(msg.get("model", ""))
        toks = msg.get("tokens", {}) or {}
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
        for tc in msg.get("toolCalls", []) or []:
            if not isinstance(tc, dict):
                continue
            name = str(tc.get("name", tc.get("tool", "tool")))
            rec.tools[name] += 1
        thoughts_blocks = msg.get("thoughts", []) or []
        if isinstance(thoughts_blocks, list):
            for th in thoughts_blocks:
                rec.buckets["thinking"] += len(str(th if isinstance(th, str) else th.get("text", th.get("summary", "")))) // 8
        elif thoughts_blocks and not isinstance(thoughts_blocks, list):
            rec.buckets["thinking"] += len(str(thoughts_blocks)) // 8
        if not rec.started:
            rec.started = ts
    # info | error | warning and control lines: skipped


def _accumulate_legacy(rec: SessionRecord, r: dict) -> None:
    """Fold one old array-of-records entry ({type: user|gemini, text})."""
    t = r.get("type", "")
    if t == "user":
        rec.n_messages += 1
        rec.buckets["user"] += len(str(r.get("text", ""))) // 4
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


def _project_name(tmp: Path, project_hash: str) -> str:
    """Best-effort project_hash -> working directory via projects.json / .project_root."""
    if not project_hash:
        return ""
    try:
        pmap = json.loads((tmp / "projects.json").read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        pmap = None
    if isinstance(pmap, dict):
        for k, v in pmap.items():
            if v == project_hash or (isinstance(v, dict) and project_hash in {str(x) for x in v.values()}):
                return str(k)
            if isinstance(v, str) and project_hash in v:
                return str(k)
    try:
        root_file = tmp / project_hash / ".project_root"
        if root_file.exists():
            return root_file.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        pass
    return project_hash


def parse_file(path: Path, project: str, tmp: Path | None = None) -> SessionRecord:
    rec = SessionRecord(session_id=path.stem, agent="gemini", project=project)
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return rec

    if path.suffix == ".jsonl":
        session_start = 0.0
        pending: list[dict] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(o, dict):
                continue
            if "sessionId" in o and "type" not in o:
                # metadata line
                rec.session_id = str(o.get("sessionId", rec.session_id))
                session_start = _to_epoch(o.get("startTime"))
                rec.started = session_start
                dirs = o.get("directories") or []
                if dirs:
                    rec.project = str(dirs[0])
                elif tmp is not None:
                    resolved = _project_name(tmp, str(o.get("projectHash", "")))
                    if resolved:
                        rec.project = resolved
                continue
            if "$rewindTo" in o or "$set" in o:
                continue  # control lines carry no billable signal
            if "type" in o:
                pending.append(o)
        for m in pending:
            _accumulate(rec, m, session_start)
        return rec

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return rec
    if isinstance(data, dict):
        # legacy whole-session {sessionId, startTime, messages:[...]}
        rec.session_id = str(data.get("sessionId", rec.session_id))
        session_start = _to_epoch(data.get("startTime"))
        if session_start:
            rec.started = session_start
        messages = data.get("messages", data.get("records", []))
        if isinstance(messages, list):
            for m in messages:
                if not isinstance(m, dict):
                    continue
                if "content" in m or m.get("type") in ("user", "gemini", "model"):
                    _accumulate(rec, m, session_start)
        return rec
    records = data if isinstance(data, list) else []
    for r in records:
        if isinstance(r, dict):
            _accumulate_legacy(rec, r)
    return rec


def _resolve_tmp(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return Path(explicit)
    home = os.environ.get("GEMINI_CLI_HOME")
    if home:
        return Path(home).expanduser() / ".gemini" / "tmp"
    return Path.home() / ".gemini" / "tmp"


def scan(root: Path | None = None) -> list[SessionRecord]:
    tmp = _resolve_tmp(root)
    out: list[SessionRecord] = []
    if not tmp.exists():
        return out
    seen: set[str] = set()
    for chats in sorted(tmp.glob("*/chats")):
        project = _project_name(tmp, chats.parent.name)
        for f in sorted(chats.rglob("*.jsonl")) + sorted(chats.rglob("*.json")):
            key = str(f)
            if key in seen or f.name == "projects.json":
                continue
            seen.add(key)
            try:
                rec = parse_file(f, project, tmp)
                if rec.n_messages or rec.total_tokens:
                    out.append(rec)
            except Exception:
                continue
    return out
