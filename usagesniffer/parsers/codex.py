"""Codex parser: ~/.codex/sessions/**/*.jsonl (rollout files)

Observed format: one JSON object per line with {timestamp, type, payload}.
- type == "session_meta": cwd, model_provider, cli_version.
- type == "event_msg" with payload.type == "token_count":
  payload.info.total_token_usage / last_token_usage carry
  input_tokens / cached_input_tokens / output_tokens /
  reasoning_output_tokens / total_tokens. This is the ONLY ground-truth
  token signal; everything else is attribution heuristics.
- type == "response_item": tool calls (custom_tool_call with exec input,
  function_call, local_shell_call), developer messages containing
  <skills_instructions> blocks and SKILL.md-heavy prompts.

Attribution per token_count delta (last_token_usage):
- reasoning_output_tokens -> thinking
- cached_input_tokens    -> context_cache
- output - reasoning      -> split assistant_text vs tools by whether
  tool calls happened since the previous token_count event
- input - cached          -> system/context base, plus a skills share when
  skill instructions or SKILL.md reads appear in the window.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from ..models import SessionRecord

SKILL_RE = re.compile(r"SKILL\.md|skills/([\w\-\.]+)", re.I)
TOOL_NAME_KEYS = ("name", "command", "cmd")


def _payload_text(payload) -> str:
    try:
        return json.dumps(payload, ensure_ascii=False)[:6000]
    except Exception:
        return str(payload)[:6000]


def parse_file(path: Path) -> SessionRecord:
    rec = SessionRecord(session_id=path.stem, agent="codex")
    pending_tools: Counter = Counter()
    pending_skill_hits = 0
    pending_text_chars = 0
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return rec
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = o.get("type")
        payload = o.get("payload", {}) or {}
        if t == "session_meta":
            rec.cwd = str(payload.get("cwd", rec.cwd))
            rec.model = str(payload.get("model_provider", rec.model or "codex"))
            rec.project = rec.cwd
        elif t == "response_item":
            ptype = payload.get("type", "")
            if ptype in ("custom_tool_call", "function_call", "local_shell_call",
                         "shell_call", "exec"):
                name = str(payload.get("name", payload.get("command", "exec")))
                pending_tools[name] += 1
                rec.tools[name] += 1
                pending_text_chars += len(_payload_text(payload.get("input", payload)))
            elif ptype == "message":
                txt = _payload_text(payload.get("content", ""))
                pending_text_chars += len(txt)
                for m in SKILL_RE.finditer(txt):
                    skill = (m.group(1) or "skill-instructions").strip("/.").lower()[:40]
                    rec.skills[skill] += 1
                    pending_skill_hits += 1
            elif ptype == "custom_tool_call_output":
                pending_text_chars += len(_payload_text(payload.get("output", ""))[:2000])
            else:
                pending_text_chars += len(_payload_text(payload)[:500])
        elif t == "event_msg":
            if payload.get("type") != "token_count":
                # still count tool completions for the window
                if payload.get("type") == "item_completed":
                    item = payload.get("item", {}) or {}
                    if isinstance(item, dict) and item.get("type"):
                        pending_tools[item["type"]] += 1
                continue
            info = payload.get("info", {}) or {}
            last = info.get("last_token_usage", info.get("total_token_usage", {})) or {}
            inp = int(last.get("input_tokens", 0) or 0)
            cached = int(last.get("cached_input_tokens", 0) or 0)
            out = int(last.get("output_tokens", 0) or 0)
            reasoning = int(last.get("reasoning_output_tokens", 0) or 0)
            rec.input_tokens += inp
            rec.output_tokens += out
            rec.cache_read += cached
            rec.reasoning_tokens += reasoning
            rec.buckets["thinking"] += reasoning
            rec.buckets["context_cache"] += cached
            base_in = max(0, inp - cached)
            # skills share of fresh input
            if pending_skill_hits:
                share = min(base_in, base_in // 2 + pending_skill_hits * 200)
                rec.buckets["skills"] += share
                base_in -= share
            # tools share of fresh input + non-reasoning output
            nontool_out = max(0, out - reasoning)
            if pending_tools:
                rec.buckets["tools"] += base_in // 2 + nontool_out // 2
                rec.buckets["assistant_text"] += nontool_out - nontool_out // 2
                rec.buckets["system"] += base_in - base_in // 2
            else:
                rec.buckets["assistant_text"] += nontool_out
                rec.buckets["system"] += base_in
            rec.n_messages += 1
            pending_tools = Counter()
            pending_skill_hits = 0
            pending_text_chars = 0
    return rec


def scan(root: Path | None = None) -> list[SessionRecord]:
    root = root or (Path.home() / ".codex" / "sessions")
    out: list[SessionRecord] = []
    if not root.exists():
        return out
    files = sorted(root.rglob("*.jsonl"))
    for f in files:
        try:
            out.append(parse_file(f))
        except Exception:
            continue
    return out
