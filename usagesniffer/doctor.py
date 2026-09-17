"""Proactive cost/efficiency audits. Read-only: diagnoses waste, never deletes.

Checks:
1. skill_weight  — SKILL.md files that are large AND loaded often (context tax
   paid every session). Suggests slimming or lazy-loading.
2. output_hogs   — tool calls whose output payloads dominate context
   (e.g. dumping whole files/logs into the transcript). Suggests targeted
   reads (rg/sed ranges) instead of cat-everything.
3. model_fit     — expensive-model sessions doing routine tool-heavy work with
   near-zero thinking share. Estimates savings of a cheaper model.
4. cache_reuse   — pricey sessions with low cache-hit share (short sessions
   that never benefit from caching, or cache-hostile patterns).
5. disk          — session stores that have grown large on disk.
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path

from .pricing import fmt_dollars, session_cost

CHEAP_EQUIV = {  # expensive substring -> cheaper alternative ($/M in,out)
    "opus": ("haiku", (0.8, 4.0)),
    "sonnet": ("haiku", (0.8, 4.0)),
    "gpt-5": ("gpt-5-mini", (0.6, 2.4)),
    "gpt-4o": ("gpt-5-mini", (0.6, 2.4)),
    "pro": ("flash", (0.3, 2.5)),
}


def audit_skill_weight(sessions, skills_dir: Path | None = None) -> list[dict]:
    """Size x frequency for skills actually observed in logs."""
    skills_dir = skills_dir or (Path.home() / ".agents" / "skills")
    freq: Counter = Counter()
    for s in sessions:
        freq.update(s.skills)
    sizes: dict[str, int] = {}
    if skills_dir.exists():
        for child in skills_dir.iterdir():
            f = child / "SKILL.md" if child.is_dir() else None
            if f and f.exists():
                try:
                    sizes[child.name.lower()] = f.stat().st_size
                except OSError:
                    pass
    findings = []
    for skill, n in freq.most_common(30):
        kb = sizes.get(skill, 0) // 1024
        if kb >= 8 and n >= 3:  # heavy + loaded often
            findings.append({
                "check": "skill_weight", "severity": "med" if kb < 30 else "high",
                "detail": f"skill '{skill}' ~{kb}KB loaded in {n} sessions "
                          f"(~{kb*n}KB cumulative context tax)",
                "fix": f"Slim {skill}/SKILL.md (front-load triggers, move depth to references) "
                       f"or load it on-demand instead of every session.",
            })
    return findings


def _claude_output_hogs(limit_sessions: int = 60) -> list[dict]:
    """Map tool_use ids to names, then sum tool_result payload chars per tool."""
    root = Path.home() / ".claude" / "projects"
    per_tool: Counter = Counter()
    per_session: Counter = Counter()
    files = sorted(root.rglob("*.jsonl")) if root.exists() else []
    # heaviest files first (approx by size) so the limit covers what matters
    files = sorted(files, key=lambda f: f.stat().st_size if f.exists() else 0, reverse=True)[:limit_sessions]
    for f in files:
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        names: dict[str, str] = {}
        for line in lines:
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            if o.get("type") == "assistant":
                for b in (o.get("message", {}) or {}).get("content", []) or []:
                    if b.get("type") == "tool_use" and b.get("id"):
                        names[b["id"]] = str(b.get("name", "tool"))
            elif o.get("type") == "user":
                content = (o.get("message", {}) or {}).get("content", "")
                if isinstance(content, list):
                    for b in content:
                        if isinstance(b, dict) and b.get("type") == "tool_result":
                            name = names.get(b.get("tool_use_id", ""), "tool")
                            n = len(json.dumps(b.get("content", ""), ensure_ascii=False))
                            per_tool[name] += n
                            per_session[f.stem] += n
    findings = []
    for tool, chars in per_tool.most_common(8):
        tok = chars // 4
        if tok > 100_000:
            findings.append({
                "check": "output_hogs", "severity": "high" if tok > 500_000 else "med",
                "detail": f"Claude tool '{tool}' dumped ~{tok:,} tokens of output into transcripts",
                "fix": "Prefer targeted reads (rg, sed -n ranges, --max-count) over "
                       "dumping whole files/logs; summarize before pasting.",
            })
    for sess, chars in per_session.most_common(5):
        if chars // 4 > 300_000:
            findings.append({
                "check": "output_hogs", "severity": "med",
                "detail": f"session {sess[:12]} absorbed ~{chars//4:,} tokens of tool output",
                "fix": "Mid-session /compact (or fresh session) after heavy exploration phases.",
            })
    return findings


def _opencode_output_hogs(top: int = 8) -> list[dict]:
    from .parsers.opencode import _db_path
    dbp = _db_path()
    if not dbp:
        return []
    try:
        con = sqlite3.connect(f"file:{dbp}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return []
    per_tool: Counter = Counter()
    try:
        for (data,) in con.execute("SELECT data FROM part WHERE data LIKE '%\"type\":\"tool\"%' LIMIT 20000"):
            try:
                p = json.loads(data)
            except (json.JSONDecodeError, TypeError):
                continue
            state = p.get("state", {}) or {}
            out = state.get("output", state.get("metadata", ""))
            per_tool[str(p.get("tool", "tool"))] += len(json.dumps(out, ensure_ascii=False))
    except sqlite3.Error:
        pass
    finally:
        con.close()
    findings = []
    for tool, chars in per_tool.most_common(top):
        if chars // 4 > 100_000:
            findings.append({
                "check": "output_hogs", "severity": "med",
                "detail": f"Opencode tool '{tool}' produced ~{chars//4:,} tokens of output",
                "fix": "Scope bash/read calls narrowly; avoid piping bulk output back to the agent.",
            })
    return findings


def audit_model_fit(sessions) -> list[dict]:
    findings = []
    for s in sessions:
        c = session_cost(s)
        if c["total"] < 5:  # only sessions worth re-routing
            continue
        noncache = sum(s.buckets.values()) - s.buckets.get("context_cache", 0) or 1
        think_share = s.buckets.get("thinking", 0) / noncache
        m = s.model.lower()
        for key, (alt, rate) in CHEAP_EQUIV.items():
            if key in m and think_share < 0.02 and sum(s.tools.values()) >= 5:
                cheap = session_cost(s, rate)["total"]
                saved = c["total"] - cheap
                if saved > 2:
                    findings.append({
                        "check": "model_fit", "severity": "high" if saved > 20 else "med",
                        "detail": f"[{s.agent}] {s.session_id[:12]} on {s.model}: "
                                  f"{fmt_dollars(c['total'])}, thinking {think_share*100:.1f}%, "
                                  f"{sum(s.tools.values())} tool calls (routine work)",
                        "fix": f"Route this class of task to {alt}: est. saving {fmt_dollars(saved)}/session.",
                        "saved": saved,
                    })
                break
    return sorted(findings, key=lambda f: -f.get("saved", 0))[:15]


def audit_cache_reuse(sessions) -> list[dict]:
    findings = []
    for s in sessions:
        c = session_cost(s)
        if c["total"] < 5:
            continue
        prompt = s.input_tokens + s.cache_read or 1
        hit = s.cache_read / prompt
        if hit < 0.5:
            findings.append({
                "check": "cache_reuse", "severity": "med",
                "detail": f"[{s.agent}] {s.session_id[:12]} {fmt_dollars(c['total'])} "
                          f"with only {hit*100:.0f}% cache-hit share",
                "fix": "Longer-lived sessions in one cwd compact better; avoid restarts that "
                       "throw away warm cache. (Opencode/Codex sessions in one dir reuse most.)",
            })
    return findings[:10]


def audit_disk() -> list[dict]:
    cands = {
        "claude projects": Path.home() / ".claude" / "projects",
        "codex sessions": Path.home() / ".codex" / "sessions",
        "opencode.db": Path.home() / ".local" / "share" / "opencode" / "opencode.db",
        "gemini tmp": Path.home() / ".gemini" / "tmp",
        "copilot store": Path.home() / ".copilot" / "session-store.db",
    }
    findings = []
    for name, p in cands.items():
        if not p.exists():
            continue
        try:
            size = p.stat().st_size if p.is_file() else sum(
                f.stat().st_size for f in p.rglob("*") if f.is_file())
        except OSError:
            continue
        mb = size / 1e6
        if mb > 500:
            findings.append({
                "check": "disk", "severity": "med",
                "detail": f"{name} occupies {mb:,.0f}MB on disk",
                "fix": "Archive/prune sessions older than your retention need "
                       "(export first — deletion is irreversible and out of scope here).",
            })
    return findings


def run_all(sessions) -> list[dict]:
    out: list[dict] = []
    out += audit_skill_weight(sessions)
    try:
        out += _claude_output_hogs()
    except Exception:
        pass
    try:
        out += _opencode_output_hogs()
    except Exception:
        pass
    out += audit_model_fit(sessions)
    out += audit_cache_reuse(sessions)
    out += audit_disk()
    order = {"high": 0, "med": 1, "low": 2}
    return sorted(out, key=lambda f: order.get(f["severity"], 2))
