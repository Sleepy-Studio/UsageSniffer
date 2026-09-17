"""Track 5: anomaly detection, skill ROI, cross-agent comparison.

All heuristics over SessionRecord aggregates — cheap, explainable, no ML.
"""
from __future__ import annotations

from collections import Counter


def detect_anomalies(sessions, thresh: float = 4.0) -> list[dict]:
    """Flag sessions whose bucket/tool shares deviate from the agent baseline.

    Compares each session's non-cache bucket mix against the median mix of
    its agent peers. Returns findings sorted by severity.
    """
    by_agent: dict[str, list] = {}
    for s in sessions:
        by_agent.setdefault(s.agent, []).append(s)
    findings: list[dict] = []
    for agent, ss in by_agent.items():
        if len(ss) < 3:
            continue
        # baseline: median share per bucket across peers (non-cache)
        buckets = ["thinking", "skills", "tools", "assistant_text", "system", "user"]
        med: dict[str, float] = {}
        for b in buckets:
            shares = sorted(
                (s.buckets.get(b, 0) / (sum(s.buckets.values()) - s.buckets.get("context_cache", 0) or 1))
                for s in ss
            )
            med[b] = shares[len(shares) // 2]
        for s in ss:
            denom = sum(s.buckets.values()) - s.buckets.get("context_cache", 0) or 1
            if denom < 100_000:
                continue  # tiny sessions: shares are noise, skip share findings
            for b in buckets:
                share = s.buckets.get(b, 0) / denom
                base = med[b] or 0.02
                if share > base * thresh and s.buckets.get(b, 0) > 20_000:
                    findings.append({
                        "session": s.session_id, "agent": agent, "bucket": b,
                        "share": share, "baseline": base,
                        "ratio": share / base, "tokens": int(s.buckets[b]),
                    })
        # tool-count outliers: sessions with 3x median tool calls
        counts = sorted(sum(s.tools.values()) for s in ss)
        med_tools = counts[len(counts) // 2] or 1
        for s in ss:
            n = sum(s.tools.values())
            if n > med_tools * 3 and n > 30:
                findings.append({
                    "session": s.session_id, "agent": agent, "bucket": "tool-count",
                    "share": 0.0, "baseline": float(med_tools),
                    "ratio": n / med_tools, "tokens": n,
                })
    return sorted(findings, key=lambda f: -f["ratio"])


def skill_roi(sessions) -> list[dict]:
    """Per-skill: sessions touched, median session cost proxy (tokens).

    Cheap sessions using a skill suggest leverage; expensive ones suggest
    token pits. Cost proxy = total tokens (model-agnostic).
    """
    from .pricing import session_cost
    stats: dict[str, list[float]] = {}
    for s in sessions:
        if not s.skills:
            continue
        c = session_cost(s)["total"]
        for skill in s.skills:
            stats.setdefault(skill, []).append(c)
    rows = []
    for skill, costs in stats.items():
        costs.sort()
        rows.append({
            "skill": skill, "sessions": len(costs),
            "median_cost": costs[len(costs) // 2],
            "total_cost": sum(costs),
        })
    return sorted(rows, key=lambda r: -r["total_cost"])


def compare_agents(sessions) -> list[dict]:
    """Per-agent efficiency: cost per message, thinking share, tool intensity."""
    from .pricing import total_cost
    by_agent: dict[str, list] = {}
    for s in sessions:
        by_agent.setdefault(s.agent, []).append(s)
    rows = []
    for agent, ss in sorted(by_agent.items()):
        msgs = sum(s.n_messages for s in ss) or 1
        tc = total_cost(ss)["total"]
        think = sum(s.buckets.get("thinking", 0) for s in ss)
        noncache = sum(sum(s.buckets.values()) - s.buckets.get("context_cache", 0) for s in ss) or 1
        rows.append({
            "agent": agent, "sessions": len(ss), "messages": msgs,
            "total_cost": tc, "cost_per_msg": tc / msgs,
            "thinking_share": think / noncache,
            "tools_per_msg": sum(sum(s.tools.values()) for s in ss) / msgs,
        })
    return sorted(rows, key=lambda r: -r["total_cost"])
