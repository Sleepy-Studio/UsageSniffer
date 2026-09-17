"""Burn over time: per-day token + cost chart from session timestamps.

Sessions with unknown start are reported once as a separate line, never
silently folded into a day.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from .pricing import fmt_dollars, session_cost


def bucketize(sessions, days: int):
    now = datetime.now(timezone.utc)
    per_day_tokens: Counter = Counter()
    per_day_cost: Counter = Counter()
    unknown_tokens = unknown_cost = 0
    unknown_n = 0
    for s in sessions:
        c = session_cost(s)["total"]
        if s.started:
            d = datetime.fromtimestamp(s.started, timezone.utc).date().isoformat()
            per_day_tokens[d] += s.total_tokens
            per_day_cost[d] += c
        else:
            unknown_tokens += s.total_tokens
            unknown_cost += c
            unknown_n += 1
    estreia = (now - timedelta(days=days - 1)).date()
    rows = []
    for i in range(days):
        d = (estreia + timedelta(days=i)).isoformat()
        rows.append((d, per_day_tokens.get(d, 0), per_day_cost.get(d, 0.0)))
    return rows, {"tokens": unknown_tokens, "cost": unknown_cost, "n": unknown_n}


def render_burn(sessions, days: int, width: int = 34) -> str:
    rows, unk = bucketize(sessions, days)
    peak = max(([t for _, t, _ in rows] or [0]) + [1])
    L = [f"--- token burn, last {days}d (per-day totals) ---"]
    for d, tok, cost in rows:
        n = int(round(tok / peak * width)) if peak else 0
        bar = "█" * n + "░" * (width - n)
        k = f"{tok/1e6:.2f}M" if tok >= 1e6 else f"{tok/1e3:.1f}k" if tok >= 1e3 else str(tok)
        L.append(f"  {d} {bar} {k:>8}  {fmt_dollars(cost):>9}")
    total_cost = sum(c for _, _, c in rows)
    L.append(f"  period cost: {fmt_dollars(total_cost)}"
             + (f"  (+{fmt_dollars(unk['cost'])} across {unk['n']} undated sessions)" if unk["n"] else ""))
    return "\n".join(L)
