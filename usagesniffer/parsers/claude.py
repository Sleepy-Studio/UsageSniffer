"""Claude Code parser: ~/.claude/projects/<slug>/*.jsonl

Format notes (observed):
- one JSON object per line, `type` in {user, assistant, attachment,
  mode, permission-mode, file-history-snapshot, ...}
- assistant entries carry message.content[] blocks:
  thinking / text / tool_use, plus message.usage with
  input_tokens / output_tokens / cache_creation_input_tokens /
  cache_read_input_tokens.
- user entries carry message.content[] with text / tool_result blocks.

Attribution (honest heuristic, labelled as estimate in UI):
- output_tokens are split across thinking / assistant_text / tools
  proportional to block char sizes in that message.
- input + cache tokens go to context_cache / context_write / user / system.
  tool_result char volume is tracked for the tools-share estimate.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from ..models import SessionRecord

SKILL_RE = re.compile(r"SKILL\.md|/skills/([\w\-]+)|skills_instructions|Skill\s*\(\s*['\"]?([\w\-]+)", re.I)
# Intentionally narrow: bare "skill <word>" prose matches are too noisy,
# so skill attribution requires an explicit SKILL.md path, /skills/ path,
# skills_instructions block, or a Skill-named tool. Plain "skill" words
# are counted separately as weak hints (not added to buckets).
WEAK_SKILL_RE = re.compile(r"\bskill\b", re.I)


def _chars(o) -> int:
    try:
        return len(json.dumps(o, ensure_ascii=False))
    except Exception:
        return len(str(o))


def parse_file(path: Path, project_slug: str) -> SessionRecord:
    rec = SessionRecord(session_id=path.stem, agent="claude", project=project_slug)
    tool_result_chars = 0
    user_chars = 0
    system_chars = 0
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
        if t == "assistant":
            msg = o.get("message", {}) or {}
            if not rec.model:
                rec.model = str(msg.get("model", ""))
            rec.n_messages += 1
            usage = msg.get("usage", {}) or {}
            inp = int(usage.get("input_tokens", 0) or 0)
            out = int(usage.get("output_tokens", 0) or 0)
            cw = int(usage.get("cache_creation_input_tokens", 0) or 0)
            cr = int(usage.get("cache_read_input_tokens", 0) or 0)
            rec.input_tokens += inp
            rec.output_tokens += out
            rec.cache_write += cw
            rec.cache_read += cr
            rec.buckets["context_cache"] += cr
            rec.buckets["context_write"] += cw
            rec.buckets["user"] += 0  # input side counted via user msgs below (chars only)
            blocks = msg.get("content", []) or []
            think_c = sum(len(b.get("thinking", "")) for b in blocks if b.get("type") == "thinking")
            text_c = sum(len(b.get("text", "")) for b in blocks if b.get("type") == "text")
            tool_c = sum(_chars(b.get("input", "")) + len(b.get("name", "")) for b in blocks if b.get("type") == "tool_use")
            denom = think_c + text_c + tool_c
            if denom > 0 and out > 0:
                rec.buckets["thinking"] += round(out * think_c / denom)
                rec.buckets["assistant_text"] += round(out * text_c / denom)
                rec.buckets["tools"] += round(out * tool_c / denom)
            elif out > 0:
                rec.buckets["assistant_text"] += out
            for b in blocks:
                if b.get("type") == "tool_use":
                    name = str(b.get("name", "unknown"))
                    rec.tools[name] += 1
                    blob = json.dumps(b.get("input", ""), ensure_ascii=False)
                    m = SKILL_RE.search(blob + " " + name)
                    if m:
                        skill = (m.group(1) or m.group(2) or "skill").lower()
                        rec.skills[skill] += 1
                        rec.buckets["skills"] += max(1, int(out * 0.05)) if out else 1
                    elif name.lower() == "skill":
                        # Explicit Skill tool call with a name in input
                        try:
                            inp = b.get("input", {})
                            sname = str(inp.get("skill", inp.get("name", "skill")))[:40].lower()
                        except Exception:
                            sname = "skill"
                        rec.skills[sname] += 1
                        rec.buckets["skills"] += max(1, int(out * 0.05)) if out else 1
        elif t == "user":
            rec.n_messages += 1
            msg = o.get("message", {}) or {}
            content = msg.get("content", "")
            if isinstance(content, str):
                user_chars += len(content)
                if "SKILL" in content.upper() or "AGENTS.md" in content:
                    system_chars += len(content) // 2
            elif isinstance(content, list):
                for b in content:
                    if not isinstance(b, dict):
                        user_chars += len(str(b))
                        continue
                    if b.get("type") == "tool_result":
                        tool_result_chars += _chars(b.get("content", ""))
                    else:
                        user_chars += len(str(b.get("text", b))[:2000])
    # Input-side estimate: tool results are the dominant context filler.
    rec.buckets["tools"] += 0  # output-side already counted; input side lives in cache buckets
    rec.buckets["system"] += system_chars // 4
    rec.buckets["user"] += user_chars // 4
    rec.buckets["other"] += tool_result_chars // 4 * 0  # tracked via counts, not double-counted
    rec.n_tool_result_chars = tool_result_chars  # type: ignore[attr-defined]
    rec.n_user_chars = user_chars  # type: ignore[attr-defined]
    return rec


def scan(root: Path | None = None) -> list[SessionRecord]:
    root = root or (Path.home() / ".claude" / "projects")
    out: list[SessionRecord] = []
    if not root.exists():
        return out
    for slug_dir in sorted(root.iterdir()):
        if not slug_dir.is_dir():
            continue
        for f in sorted(slug_dir.glob("*.jsonl")):
            try:
                out.append(parse_file(f, slug_dir.name))
            except Exception:
                continue
    return out
