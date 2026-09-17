"""Machine-readable export: sessions, buckets, tools, skills, costs as JSON."""
from __future__ import annotations

import json

from .analyze import aggregate
from .pricing import session_cost, total_cost


def export_json(sessions) -> dict:
    t = aggregate(sessions)
    tc = total_cost(sessions)
    return {
        "sessions": len(sessions),
        "totals": {
            "input": t.input, "output": t.output,
            "cache_read": t.cache_read, "cache_write": t.cache_write,
            "reasoning": t.reasoning, "grand": t.grand,
        },
        "cost": tc,
        "buckets": {k: int(v) for k, v in t.buckets.items()},
        "tools": dict(t.tools.most_common(50)),
        "skills": dict(t.skills.most_common(50)),
        "sessions_detail": [
            {
                "id": s.session_id, "agent": s.agent, "project": s.project,
                "cwd": s.cwd, "model": s.model, "started": s.started,
                "messages": s.n_messages,
                "tokens": {"input": s.input_tokens, "output": s.output_tokens,
                           "cache_read": s.cache_read, "cache_write": s.cache_write,
                           "reasoning": s.reasoning_tokens, "total": s.total_tokens},
                "buckets": {k: int(v) for k, v in s.buckets.items()},
                "tools": dict(s.tools), "skills": dict(s.skills),
                "cost": session_cost(s),
            }
            for s in sorted(sessions, key=lambda s: s.total_tokens, reverse=True)
        ],
    }


def dumps(sessions) -> str:
    return json.dumps(export_json(sessions), indent=1)
