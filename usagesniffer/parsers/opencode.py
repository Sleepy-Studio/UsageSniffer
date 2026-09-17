"""Opencode parser: ~/.local/share/opencode/opencode.db (SQLite)

Tables (observed): session(id, title, directory, model, tokens_input,
tokens_output, tokens_reasoning, tokens_cache_read, tokens_cache_write,
time_created...), message(id, session_id, data JSON with role/tokens/...),
part(id, message_id, session_id, data JSON with type in
{text, reasoning, tool, step-start, step-finish, ...}).

Ground truth: message.data.tokens {input, output, reasoning,
cache:{read, write}} on assistant messages + session rollups.
Attribution: per assistant message, reasoning -> thinking,
cache -> context buckets, remaining input/output split across
text vs tool parts by char size. Tool names from part.tool,
skill hits via SKILL.md / 'skill' mentions in text/tool input.
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

from ..models import SessionRecord

SKILL_RE = re.compile(r"SKILL\.md|\bskill\b", re.I)


def _chars(o) -> int:
    try:
        return len(json.dumps(o, ensure_ascii=False))
    except Exception:
        return len(str(o))


def _db_path(explicit: Path | None = None) -> Path | None:
    import os
    if explicit:
        return explicit if explicit.exists() else None  # strict: override means "look here only"
    # Explicit override wins (covers OPENCODE_DB-injected Roaming splits on Windows).
    env = os.environ.get("OPENCODE_DB")
    if env and Path(env).exists():
        return Path(env)
    cands = [Path.home() / ".local" / "share" / "opencode" / "opencode.db"]
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            # legacy/alternate location some integrations use
            cands.append(Path(appdata) / "opencode" / "opencode.db")
            cands.append(Path(appdata) / "Roaming" / "opencode" / "opencode.db")
    for c in cands:
        if c.exists():
            return c
    return None


def scan(db: Path | None = None) -> list[SessionRecord]:
    dbp = _db_path(db)
    if not dbp:
        return []
    con = sqlite3.connect(str(dbp))
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    try:
        sessions = cur.execute(
            "SELECT id, title, directory, model, tokens_input, tokens_output,"
            " tokens_reasoning, tokens_cache_read, tokens_cache_write,"
            " time_created FROM session"
        ).fetchall()
    except sqlite3.Error:
        return []
    out: list[SessionRecord] = []
    for s in sessions:
        sid = s["id"]
        rec = SessionRecord(
            session_id=sid,
            agent="opencode",
            project=str(s["title"] or ""),
            cwd=str(s["directory"] or ""),
            model=str(s["model"] or ""),
        )
        try:
            rec.started = float(s["time_created"] or 0) / 1000
        except (TypeError, ValueError):
            pass
        try:
            msgs = cur.execute("SELECT id, data FROM message WHERE session_id=?", (sid,)).fetchall()
        except sqlite3.Error:
            continue
        msg_ids = [m["id"] for m in msgs]
        parts_by_msg: dict[str, list[dict]] = {mid: [] for mid in msg_ids}
        if msg_ids:
            qmarks = ",".join("?" for _ in msg_ids)
            try:
                for row in cur.execute(
                    f"SELECT message_id, data FROM part WHERE message_id IN ({qmarks})", msg_ids
                ).fetchall():
                    try:
                        parts_by_msg.setdefault(row["message_id"], []).append(json.loads(row["data"]))
                    except (json.JSONDecodeError, TypeError):
                        continue
            except sqlite3.Error:
                pass
        for m in msgs:
            try:
                data = json.loads(m["data"])
            except (json.JSONDecodeError, TypeError):
                continue
            role = data.get("role", "")
            rec.n_messages += 1
            toks = data.get("tokens", {}) or {}
            cache = toks.get("cache", {}) or {}
            inp = int(toks.get("input", 0) or 0)
            outp = int(toks.get("output", 0) or 0)
            rsn = int(toks.get("reasoning", 0) or 0)
            cr = int(cache.get("read", 0) or 0)
            cwr = int(cache.get("write", 0) or 0)
            rec.input_tokens += inp
            rec.output_tokens += outp
            rec.reasoning_tokens += rsn
            rec.cache_read += cr
            rec.cache_write += cwr
            if role != "assistant":
                rec.buckets["user"] += inp // 4 + outp // 4
                continue
            rec.buckets["thinking"] += rsn
            rec.buckets["context_cache"] += cr
            rec.buckets["context_write"] += cwr
            parts = parts_by_msg.get(m["id"], [])
            text_c = sum(len(p.get("text", "")) for p in parts if p.get("type") == "text")
            rsn_c = sum(len(p.get("text", "")) for p in parts if p.get("type") == "reasoning")
            tool_ps = [p for p in parts if p.get("type") == "tool"]
            tool_c = sum(_chars(p.get("state", {}).get("input", p)) for p in tool_ps)
            # split leftover (non-reasoning, non-cache) across text/tools
            left_in = max(0, inp - cr)
            left_out = max(0, outp - rsn)
            denom = text_c + tool_c
            if denom > 0:
                rec.buckets["assistant_text"] += round(left_out * text_c / denom)
                rec.buckets["tools"] += round(left_out * tool_c / denom) + left_in * tool_c // denom
                rec.buckets["system"] += left_in * text_c // denom
            else:
                rec.buckets["assistant_text"] += left_out
                rec.buckets["system"] += left_in
            for p in tool_ps:
                name = str(p.get("tool", "tool"))
                rec.tools[name] += 1
            for p in parts:
                blob = json.dumps(p, ensure_ascii=False)[:3000]
                if SKILL_RE.search(blob):
                    key = "skill-ref"
                    m2 = re.search(r"skills/([\w\-]+)", blob, re.I)
                    if m2:
                        key = m2.group(1).lower()
                    rec.skills[key] += 1
                    rec.buckets["skills"] += max(50, left_in // 10)
            _ = rsn_c
        out.append(rec)
    con.close()
    return out
