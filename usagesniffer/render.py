"""Terminal renderer: stdlib-only ASCII bars + tables (rich optional)."""
from __future__ import annotations

import shutil

from .analyze import Totals, aggregate, top_sessions

BAR = "█"
DIM = "░"


def _width() -> int:
    try:
        return min(100, shutil.get_terminal_size().columns - 8)
    except Exception:
        return 72


def bar(frac: float, w: int = 34) -> str:
    frac = max(0.0, min(1.0, frac))
    full = int(round(frac * w))
    return BAR * full + DIM * (w - full)


def fmt(n: int) -> str:
    if n >= 1_000_000:
        return f"{n/1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}k"
    return str(n)


def render_overview(result, show=10) -> str:
    t: Totals = aggregate(result.sessions)
    w = _width()
    L: list[str] = []
    L.append("=" * w)
    L.append("USAGESNIFFER — what ate your tokens")
    L.append("=" * w)
    by_agent: dict[str, list] = {}
    for s in result.sessions:
        by_agent.setdefault(s.agent, []).append(s)
    L.append(f"sessions: {t.sessions}   messages/steps: {t.messages}   total tokens: {fmt(t.grand)}")
    L.append("")
    L.append("--- by agent (real token totals from logs) ---")
    for agent, ss in sorted(by_agent.items()):
        at = aggregate(ss)
        L.append(f"  {agent:<9} sessions={at.sessions:<4} total={fmt(at.grand):>8}  "
                 f"in={fmt(at.input):>7} out={fmt(at.output):>7} "
                 f"cache_read={fmt(at.cache_read):>7} cache_write={fmt(at.cache_write):>7} think={fmt(at.reasoning):>7}")
    L.append("")
    L.append("--- attribution buckets (token-weighted estimates; heuristics, not billing) ---")
    denom = sum(t.buckets.values()) or 1
    for name, val in t.buckets.most_common():
        L.append(f"  {name:<14} {bar(val/denom):<36} {fmt(int(val)):>8}  {100*val/denom:5.1f}%")
    L.append("")
    L.append("--- action share EXCLUDING context cache (where your budget actually goes) ---")
    action = {k: v for k, v in t.buckets.items() if k != "context_cache"}
    adenom = sum(action.values()) or 1
    for name, val in sorted(action.items(), key=lambda kv: -kv[1]):
        L.append(f"  {name:<14} {bar(val/adenom):<36} {fmt(int(val)):>8}  {100*val/adenom:5.1f}%")
    L.append("")
    L.append("--- top tools ---")
    for name, c in t.tools.most_common(12):
        L.append(f"  {name[:42]:<42} x{c}")
    if not t.tools:
        L.append("  (no tool calls detected)")
    L.append("")
    L.append("--- top skills ---")
    for name, c in t.skills.most_common(12):
        L.append(f"  {name[:42]:<42} x{c}")
    if not t.skills:
        L.append("  (no SKILL.md / skill refs detected)")
    L.append("")
    L.append(f"--- top {show} sessions ---")
    for s in top_sessions(result.sessions, show):
        L.append(f"  [{s.agent}] {s.session_id[:24]:<24} total={fmt(s.total_tokens):>8} "
                 f"in={fmt(s.input_tokens):>7} out={fmt(s.output_tokens):>7} "
                 f"cr={fmt(s.cache_read):>7} cw={fmt(s.cache_write):>7} {s.model[:24]}")
    L.append("")
    L.append("notes: cache_read = repeated context (cheap but bulky). thinking = reasoning blocks. "
             "skills = SKILL.md/skill-instruction shares. tools = tool I/O share.")
    return "\n".join(L)


def render_session(s) -> str:
    w = _width()
    L = [f"--- [{s.agent}] {s.session_id} ---",
         f"project: {s.project}  cwd: {s.cwd}  model: {s.model}  msgs: {s.n_messages}",
         f"tokens: total={fmt(s.total_tokens)} in={fmt(s.input_tokens)} out={fmt(s.output_tokens)} "
         f"cache_read={fmt(s.cache_read)} cache_write={fmt(s.cache_write)} reasoning={fmt(s.reasoning_tokens)}",
         "buckets:"]
    denom = sum(s.buckets.values()) or 1
    for name, val in sorted(s.buckets.items(), key=lambda kv: -kv[1]):
        L.append(f"  {name:<14} {bar(val/denom):<36} {fmt(int(val)):>8}  {100*val/denom:5.1f}%")
    if s.tools:
        L.append("tools: " + ", ".join(f"{k}x{v}" for k, v in s.tools.most_common(10)))
    if s.skills:
        L.append("skills: " + ", ".join(f"{k}x{v}" for k, v in s.skills.most_common(10)))
    return "\n".join(L)
