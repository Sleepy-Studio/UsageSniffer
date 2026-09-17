"""Hermes agent parser: ~/.hermes/state.db (SQLite, Nous Research Hermes).

Ground truth per session comes straight from the `sessions` table:
input_tokens / output_tokens / cache_read_tokens / cache_write_tokens /
reasoning_tokens, plus message_count / tool_call_count / model / cwd /
git_repo_root / title / started_at. Per-model splits live in
`session_model_usage` (used only as a model fallback).

Tool attribution is recovered from the `messages` table (role='tool' rows
carry tool_name; assistant rows carry a tool_calls JSON array with
function.name entries). Skill usage follows the repo-wide convention:
tool names containing "skill" (skill_view, skills_list, skill_manage)
plus tool-call arguments naming a skill. Buckets are token-weighted
estimates; totals are exact.
"""
from __future__ import annotations

import json
import os
import sqlite3
from collections import Counter
from pathlib import Path

from ..models import SessionRecord


def _resolve_db(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return Path(explicit)
    env = os.environ.get("HERMES_DB") or os.environ.get("HERMES_STATE_DB")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".hermes" / "state.db"


def _tool_counts(con: sqlite3.Connection) -> dict[str, Counter]:
    """session_id -> Counter(tool_name).

    Each tool execution leaves two traces: an assistant `tool_calls`
    entry and a role='tool' result row. The result rows are the
    execution count; assistant entries are only a fallback for
    sessions with no result rows (avoids 2x double-counting).
    """
    per: dict[str, Counter] = {}
    try:
        rows = con.execute(
            "SELECT session_id, tool_name FROM messages "
            "WHERE role='tool' AND tool_name IS NOT NULL"
        ).fetchall()
    except sqlite3.Error:
        rows = []
    for sid, name in rows:
        per.setdefault(str(sid), Counter())[str(name)] += 1
    have = set(per)
    try:
        arows = con.execute(
            "SELECT session_id, tool_calls FROM messages "
            "WHERE tool_calls IS NOT NULL"
        ).fetchall()
    except sqlite3.Error:
        arows = []
    for sid, blob in arows:
        if str(sid) in have:
            continue
        try:
            calls = json.loads(blob) if isinstance(blob, str) else []
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(calls, list):
            continue
        for c in calls:
            if not isinstance(c, dict):
                continue
            fn = c.get("function", {}) or {}
            name = fn.get("name") if isinstance(fn, dict) else None
            name = name or c.get("name") or c.get("tool")
            if name:
                per.setdefault(str(sid), Counter())[str(name)] += 1
    return per


def _skill_names(counter: Counter) -> Counter:
    """Skill attribution: skill-tool calls, keyed by tool name.

    Hermes exposes skills via skill_view / skills_list / skill_manage and
    generic tool_call wrappers; without per-skill argument parsing the
    stable signal is the skill-tool family itself.
    """
    skills: Counter = Counter()
    for name, n in counter.items():
        low = name.lower()
        if "skill" in low:
            skills[name] += n
    return skills


def scan(root: Path | None = None) -> list[SessionRecord]:
    dbp = _resolve_db(root)
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
        tables = {r[0] for r in cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "sessions" not in tables:
            con.close()
            return out
        sessions = cur.execute(
            "SELECT id, source, model, message_count, tool_call_count,"
            " input_tokens, output_tokens, cache_read_tokens,"
            " cache_write_tokens, reasoning_tokens, cwd, git_repo_root,"
            " title, started_at FROM sessions"
        ).fetchall()
        model_fallback: dict[str, str] = {}
        if "session_model_usage" in tables:
            try:
                for r in cur.execute(
                    "SELECT session_id, model FROM session_model_usage"
                ).fetchall():
                    sid, model = str(r[0]), str(r[1] or "")
                    if sid not in model_fallback and model:
                        model_fallback[sid] = model
            except sqlite3.Error:
                pass
    except sqlite3.Error:
        con.close()
        return out
    tools_by_session = _tool_counts(con)
    con.close()

    for s in sessions:
        try:
            sid = str(s["id"] or "")
        except (KeyError, TypeError):
            continue
        if not sid:
            continue
        model = str(s["model"] or "") or model_fallback.get(sid, "")
        cwd = str(s["cwd"] or "")
        repo = str(s["git_repo_root"] or "")
        title = str(s["title"] or "")
        project = (repo or cwd or title)[:60]
        if s["source"]:
            project = f"{s['source']}:{project}" if project else str(s["source"])
        rec = SessionRecord(
            session_id=sid, agent="hermes", project=project, cwd=cwd,
            model=model,
        )
        try:
            rec.started = float(s["started_at"] or 0.0)
        except (TypeError, ValueError):
            rec.started = 0.0
        rec.n_messages = int(s["message_count"] or 0)
        rec.input_tokens = int(s["input_tokens"] or 0)
        rec.output_tokens = int(s["output_tokens"] or 0)
        rec.cache_read = int(s["cache_read_tokens"] or 0)
        rec.cache_write = int(s["cache_write_tokens"] or 0)
        rec.reasoning_tokens = int(s["reasoning_tokens"] or 0)

        tools = tools_by_session.get(sid, Counter())
        rec.tools.update(tools)
        rec.skills.update(_skill_names(tools))

        rec.buckets["thinking"] += rec.reasoning_tokens
        rec.buckets["context_cache"] += rec.cache_read
        rec.buckets["context_write"] += rec.cache_write
        rec.buckets["assistant_text"] += max(0, rec.output_tokens - rec.reasoning_tokens)
        # Hermes counts fresh input separately from cache_read (input=42 vs
        # cache_read=1M is typical), so input is already cache-exclusive.
        rec.buckets["system"] += rec.input_tokens
        if tools:
            rec.buckets["tools"] += sum(tools.values()) * 500  # estimate marker
        if rec.skills:
            rec.buckets["skills"] += sum(rec.skills.values()) * 500
        out.append(rec)
    return out
