"""GitHub Copilot CLI parser: ~/.copilot/session-store.db (SQLite)

Verified tables: sessions(id, cwd, repository, branch, summary, ...),
assistant_usage_events(session_id, turn_index, model, input_tokens,
output_tokens, cache_read_tokens, cache_write_tokens, reasoning_tokens, ...).
turns table exists but was empty — usage events are the ground truth.

Billing is subscription-based, so dollar costs are unknown ($0 estimate);
token counts are exact. Tool names are recovered from session events.jsonl
when present (best-effort; schema is internal and version-dependent).
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from ..models import SessionRecord


def _epoch(v) -> float:
    if not v:
        return 0.0
    try:
        if isinstance(v, (int, float)):
            return float(v)
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _tools_from_events(session_dir: Path) -> Counter:
    """Best-effort tool-name recovery from events.jsonl (internal schema)."""
    c: Counter = Counter()
    f = session_dir / "events.jsonl"
    if not f.exists():
        return c
    try:
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or "tool" not in line.lower():
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            blob = json.dumps(o)[:1500]
            import re
            for m in re.finditer(r'"(?:tool|name|function)"\s*:\s*"([\w\-\.]{2,40})"', blob):
                c[m.group(1)] += 1
    except OSError:
        pass
    return c


def scan(home: Path | None = None) -> list[SessionRecord]:
    home = home or (Path.home() / ".copilot")
    dbp = home / "session-store.db"
    out: list[SessionRecord] = []
    if not dbp.exists():
        return out
    try:
        con = sqlite3.connect(f"file:{dbp}?mode=ro", uri=True)
    except sqlite3.Error:
        return out
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    try:
        sessions = cur.execute(
            "SELECT id, cwd, repository, branch, summary, created_at FROM sessions"
        ).fetchall()
        has_usage = any(
            r["name"] == "assistant_usage_events"
            for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        )
    except sqlite3.Error:
        con.close()
        return out
    for s in sessions:
        sid = s["id"]
        rec = SessionRecord(
            session_id=sid, agent="copilot",
            project=str(s["repository"] or s["summary"] or "")[:60],
            cwd=str(s["cwd"] or ""),
        )
        rec.started = _epoch(s["created_at"])
        if has_usage:
            try:
                rows = cur.execute(
                    "SELECT model, input_tokens, output_tokens, cache_read_tokens,"
                    " cache_write_tokens, reasoning_tokens FROM assistant_usage_events"
                    " WHERE session_id=?", (sid,),
                ).fetchall()
            except sqlite3.Error:
                rows = []
            for r in rows:
                if not rec.model and r["model"]:
                    rec.model = str(r["model"])
                inp = int(r["input_tokens"] or 0)
                outp = int(r["output_tokens"] or 0)
                cr = int(r["cache_read_tokens"] or 0)
                cw = int(r["cache_write_tokens"] or 0)
                rsn = int(r["reasoning_tokens"] or 0)
                rec.n_messages += 1
                rec.input_tokens += inp
                rec.output_tokens += outp
                rec.cache_read += cr
                rec.cache_write += cw
                rec.reasoning_tokens += rsn
                rec.buckets["thinking"] += rsn
                rec.buckets["context_cache"] += cr
                rec.buckets["context_write"] += cw
                rec.buckets["assistant_text"] += max(0, outp - rsn)
                rec.buckets["system"] += max(0, inp - cr)
        tools = _tools_from_events(home / "session-state" / sid)
        rec.tools.update(tools)
        if tools:
            rec.buckets["tools"] += sum(tools.values()) * 500  # estimate marker
        out.append(rec)
    con.close()
    return out
