"""Aider parser: .aider.chat.history.md transcripts + --analytics-log JSONL.

Default chat files carry NO token data — transcripts are Markdown with
'session start' headers, parsed here for message counts, tool-ish activity
(diff/SEARCH-REPLACE blocks), and char-estimated tokens (flagged estimate).

Real token/cost numbers exist only when the user sets --analytics-log:
JSONL with event=message_send, properties{main_model, prompt_tokens,
completion_tokens, total_tokens, cost, total_cost, time}. Those lines are
aggregated per analytics file as one pseudo-session each (path-derived id).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from ..models import SessionRecord

START_RE = re.compile(r"aider chat started at (.+)", re.I)


def _parse_transcript(path: Path) -> list[SessionRecord]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    # Split on session headers; ignore code fences for block counting via heuristic.
    parts = START_RE.split(text)
    out: list[SessionRecord] = []
    # parts[0] is preamble, then (date, body) pairs
    it = iter(parts[1:])
    idx = 0
    for date, body in zip(it, it):
        idx += 1
        rec = SessionRecord(session_id=f"{path.parent.name}-{idx}", agent="aider",
                            project=str(path.parent), cwd=str(path.parent))
        # crude role split: lines starting with known markers
        user_blocks = len(re.findall(r"(?m)^#{1,4}?\s*user\b|^>", body))
        rec.n_messages = max(1, body.count("\n#### ") + body.count("\n### ") + 1)
        diff_chars = len("".join(re.findall(r"(?s)```diff.*?```", body)))
        rec.tools["edit-diff"] += len(re.findall(r"SEARCH/REPLACE|<<<<<<< SEARCH", body))
        chars = len(body)
        rec.input_tokens = chars // 8
        rec.output_tokens = chars // 8
        rec.buckets["user"] += chars // 8
        rec.buckets["assistant_text"] += chars // 8
        rec.buckets["tools"] += diff_chars // 4
        _ = user_blocks
        out.append(rec)
    return out


def _parse_analytics(path: Path) -> SessionRecord | None:
    rec = SessionRecord(session_id=f"analytics-{path.parent.name}", agent="aider",
                        project=str(path.parent))
    n = 0
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            continue
        if o.get("event") != "message_send":
            continue
        p = o.get("properties", {}) or {}
        n += 1
        if not rec.model:
            rec.model = str(p.get("main_model", ""))
        rec.input_tokens += int(p.get("prompt_tokens", 0) or 0)
        rec.output_tokens += int(p.get("completion_tokens", 0) or 0)
        rec.buckets["assistant_text"] += int(p.get("completion_tokens", 0) or 0)
        rec.buckets["system"] += int(p.get("prompt_tokens", 0) or 0)
    rec.n_messages = n
    return rec if n else None


def scan(roots: list[Path] | None = None) -> list[SessionRecord]:
    out: list[SessionRecord] = []
    if roots is None:
        env = os.environ.get("AIDER_CHAT_HISTORY_FILE")
        roots = [Path(env)] if env else []
        # search common code dirs one level deep for transcripts
        for base in (Path.home() / "Documents" / "Github", Path.home() / "Projects",
                     Path.home() / "apps", Path.home() / "Work"):
            if not base.exists():
                continue
            try:
                for child in base.iterdir():
                    if child.is_dir():
                        roots.append(child / ".aider.chat.history.md")
            except OSError:
                continue
        alog = os.environ.get("AIDER_ANALYTICS_LOG")
        if alog:
            roots.append(Path(alog))
    for r in roots:
        if r.is_dir():
            for pat in (".aider.chat.history.md", ".aider.llm.history*"):
                for f in r.glob(pat):
                    out += _parse_transcript(f)
            continue
        if not r.exists():
            continue
        if r.suffix == ".jsonl" or "analytics" in r.name:
            rec = _parse_analytics(r)
            if rec:
                out.append(rec)
        else:
            out += _parse_transcript(r)
    return out
