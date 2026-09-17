"""Grok Build CLI parser: ~/.grok/sessions/<encoded-cwd>/<session-id>/

(GROK_HOME overrides ~/.grok; sessions then live at $GROK_HOME/sessions.)

Each session is a directory, not a file:
- summary.json    metadata: id, cwd, current_model_id, created_at/updated_at,
                  num_messages, generated_title
- updates.jsonl   ACP session-update stream — the authoritative token signal.
                  One `turn_completed` record per turn carries usage:
                  {inputTokens, outputTokens, cachedReadTokens,
                   cacheCreationTokens, reasoningTokens, totalTokens,
                   modelCalls, costUsdTicks, modelUsage?}.
                  Session totals are the SUM over turns (per-turn billing,
                  not a running gauge — consecutive turns rise and fall).
- chat_history.jsonl  model-protocol transcript; fallback when updates.jsonl
                  is absent (char-estimated, like Continue/Aider transcripts).
- signals.json    aggregates (camelCase): turnCount, toolCallCount,
                  toolsUsed[], modelsUsed[], primaryModelId,
                  contextTokensUsed (live context occupancy, NOT spend —
                  never mapped to totals), totalTokensBeforeCompaction.

Dollar costs are priced externally (see pricing.py); costUsdTicks is ignored.
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

from ..models import SessionRecord

SKIP_DIRS = frozenset({
    "subagents", "compaction_checkpoints", "compaction_requests",
    "terminal", "assets", "recap_requests",
})

SKILL_RE = re.compile(r"skill", re.I)

# update/sessionUpdate values that carry a tool invocation
TOOL_UPDATE_RE = re.compile(r"tool_call|function_call|execute|run_terminal|bash", re.I)


def _epoch(v) -> float:
    if not v:
        return 0.0
    try:
        if isinstance(v, (int, float)):
            return float(v / 1000) if v > 1e12 else float(v)
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _num(o, *keys) -> int:
    for k in keys:
        try:
            v = o.get(k)
        except AttributeError:
            continue
        if v is None:
            continue
        try:
            return int(v)
        except (TypeError, ValueError):
            continue
    return 0


def _find_turn_usages(obj):
    """Yield usage dicts from turn_completed records, any nesting depth."""
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            upd = cur.get("sessionUpdate", cur.get("session_update", ""))
            if upd == "turn_completed" and isinstance(cur.get("usage"), dict):
                yield cur["usage"]
            # some builds put usage beside a differently-cased marker
            elif isinstance(cur.get("usage"), dict) and upd:
                u = cur["usage"]
                if any(k in u for k in ("inputTokens", "outputTokens", "input_tokens")):
                    yield u
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)


def _tool_names_from_updates(path: Path) -> Counter:
    """Best-effort tool-name recovery from the ACP update stream."""
    c: Counter = Counter()
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return c
    for line in lines:
        line = line.strip()
        if not line or "tool" not in line.lower():
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            continue
        blob = json.dumps(o)
        if not TOOL_UPDATE_RE.search(blob):
            continue
        for m in re.finditer(r'"(?:tool|name|function|title)"\s*:\s*"([\w\-\./:]{2,60})"', blob):
            name = m.group(1).split("/")[-1].split(":")[-1]
            if name and name not in ("tool", "function"):
                c[name] += 1
                break  # one tool per event line
    return c


def _content_chars(content) -> int:
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        n = 0
        for p in content:
            if isinstance(p, dict):
                n += len(str(p.get("text", p.get("content", p.get("summary", "")))))
            else:
                n += len(str(p))
        return n
    if isinstance(content, dict):
        return len(str(content.get("text", content.get("content", ""))))
    return 0


def _parse_chat_history(path: Path, rec: SessionRecord) -> None:
    """Fallback transcript parse when updates.jsonl has no turn usage."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(o, dict):
            continue
        role = str(o.get("role", o.get("type", ""))).lower()
        content = o.get("content", o.get("message", ""))
        chars = _content_chars(content)
        if role in ("user", "human"):
            rec.n_messages += 1
            rec.buckets["user"] += chars // 4
            if not rec.started:
                rec.started = _epoch(o.get("timestamp", o.get("time", o.get("created_at"))))
        elif role in ("assistant", "ai", "model", "grok"):
            rec.n_messages += 1
            rec.output_tokens += chars // 4
            rec.buckets["assistant_text"] += chars // 4
            calls = o.get("tool_calls", o.get("toolCalls", [])) or []
            for tc in calls if isinstance(calls, list) else []:
                if not isinstance(tc, dict):
                    continue
                fn = tc.get("function", {}) or {}
                name = (fn.get("name") if isinstance(fn, dict) else None) or tc.get("name", "tool")
                rec.tools[str(name)] += 1
            if not rec.model:
                rec.model = str(o.get("model", o.get("modelId", "")))
        elif role == "tool":
            rec.buckets["tools"] += chars // 4
            name = str(o.get("name", o.get("tool", "")))
            if name:
                rec.tools[name] += 1


def parse_session(sdir: Path, group: str) -> SessionRecord:
    sid = sdir.name
    rec = SessionRecord(session_id=sid, agent="grok")

    # CWD: group dir is URL-encoded; long cwds use slug+hash with a .cwd file.
    cwd_file = sdir.parent / ".cwd"
    try:
        cwd = cwd_file.read_text(encoding="utf-8", errors="replace").strip() if cwd_file.exists() else unquote(group)
    except OSError:
        cwd = unquote(group)
    rec.cwd = cwd
    rec.project = cwd[-60:] if cwd else ""

    # --- summary.json: metadata ---
    try:
        summary = json.loads((sdir / "summary.json").read_text(encoding="utf-8", errors="replace"))
        if not isinstance(summary, dict):
            summary = {}
    except (OSError, json.JSONDecodeError):
        summary = {}
    info = summary.get("info", {}) if isinstance(summary.get("info"), dict) else {}
    rec.model = str(summary.get("current_model_id", summary.get("currentModelId", info.get("model", ""))) or "")
    rec.started = _epoch(summary.get("created_at", summary.get("createdAt", info.get("created_at"))))
    if not rec.started:
        rec.started = _epoch(summary.get("updated_at", summary.get("updatedAt")))
    n_msgs = _num(summary, "num_messages", "numMessages", "num_chat_messages", "numChatMessages")
    title = str(summary.get("generated_title", summary.get("generatedTitle", "")) or "")
    if title and not rec.project:
        rec.project = title[:60]
    if not rec.cwd:
        rec.cwd = str(info.get("cwd", info.get("working_directory", "")) or "")
        rec.project = rec.project or rec.cwd[-60:]

    # --- signals.json: counts + fallbacks (contextTokensUsed is occupancy, not spend) ---
    try:
        signals = json.loads((sdir / "signals.json").read_text(encoding="utf-8", errors="replace"))
        if not isinstance(signals, dict):
            signals = {}
    except (OSError, json.JSONDecodeError):
        signals = {}
    if not rec.model:
        rec.model = str(signals.get("primaryModelId", "") or "")
        if not rec.model:
            used = signals.get("modelsUsed", []) or []
            rec.model = str(used[0]) if used else ""
    sig_tools = Counter()
    for t in signals.get("toolsUsed", []) or []:
        sig_tools[str(t)] += 1

    # --- updates.jsonl: per-turn billing (ground truth) ---
    updates = sdir / "updates.jsonl"
    turns = 0
    if updates.exists():
        try:
            lines = updates.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            lines = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            for u in _find_turn_usages(o):
                inp = _num(u, "inputTokens", "input_tokens")
                out = _num(u, "outputTokens", "output_tokens")
                cached = _num(u, "cachedReadTokens", "cached_read_tokens", "cachedInputTokens")
                cwr = _num(u, "cacheCreationTokens", "cache_creation_tokens")
                rsn = _num(u, "reasoningTokens", "reasoning_tokens", "reasoningOutputTokens")
                if not (inp or out or cached or cwr or rsn):
                    # nested per-model usage fills fields the flat record missed
                    mu = u.get("modelUsage", u.get("model_usage", []))
                    items = mu.values() if isinstance(mu, dict) else mu if isinstance(mu, list) else []
                    for m in items if isinstance(items, list) else []:
                        if not isinstance(m, dict):
                            continue
                        inp += _num(m, "inputTokens", "input_tokens")
                        out += _num(m, "outputTokens", "output_tokens")
                        cached += _num(m, "cachedReadTokens", "cached_read_tokens")
                        cwr += _num(m, "cacheCreationTokens", "cache_creation_tokens")
                        rsn += _num(m, "reasoningTokens", "reasoning_tokens")
                    if not (inp or out or cached or cwr or rsn):
                        continue
                turns += 1
                rec.input_tokens += inp
                rec.output_tokens += out
                rec.cache_read += cached
                rec.cache_write += cwr
                rec.reasoning_tokens += rsn
                rec.buckets["thinking"] += rsn
                rec.buckets["context_cache"] += cached
                rec.buckets["context_write"] += cwr
                rec.buckets["assistant_text"] += max(0, out - rsn)
                rec.buckets["system"] += max(0, inp - cached)
                if not rec.model:
                    rec.model = str(u.get("model", u.get("modelId", "")) or "")
        tools = _tool_names_from_updates(updates)
        rec.tools.update(tools)

    if not turns:
        # No per-turn billing — fall back to the transcript (estimated).
        chat = sdir / "chat_history.jsonl"
        if chat.exists():
            _parse_chat_history(chat, rec)

    # signals.json as final fallback for counts/tools/model
    if not rec.tools and sig_tools:
        rec.tools.update(sig_tools)
    for name, n in rec.tools.items():
        if SKILL_RE.search(name):
            rec.skills[name] += n
    if rec.tools and not rec.buckets["tools"]:
        rec.buckets["tools"] += sum(rec.tools.values()) * 500  # estimate marker
    if rec.skills and not rec.buckets["skills"]:
        rec.buckets["skills"] += sum(rec.skills.values()) * 500
    if n_msgs and not rec.n_messages:
        rec.n_messages = n_msgs
    if not rec.n_messages:
        rec.n_messages = turns or _num(signals, "turn_count", "turnCount",
                                        "user_message_count", "userMessageCount")
    return rec


def _resolve_home(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return Path(explicit)
    env = os.environ.get("GROK_HOME")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".grok"


def scan(root: Path | None = None) -> list[SessionRecord]:
    home = _resolve_home(root)
    base = home if home.name == "sessions" else home / "sessions"
    out: list[SessionRecord] = []
    if not base.exists():
        return out
    for group in sorted(base.iterdir()):
        if not group.is_dir() or group.name in SKIP_DIRS:
            continue
        if group.suffix in (".sqlite", ".db"):
            continue
        for sdir in sorted(group.iterdir()):
            if not sdir.is_dir() or sdir.name in SKIP_DIRS:
                continue
            if not ((sdir / "updates.jsonl").exists()
                    or (sdir / "chat_history.jsonl").exists()
                    or (sdir / "summary.json").exists()):
                continue
            try:
                rec = parse_session(sdir, group.name)
                if rec.n_messages or rec.total_tokens:
                    out.append(rec)
            except Exception:
                continue
    return out
