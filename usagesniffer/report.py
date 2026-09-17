"""Track 3: self-contained HTML report export (no JS deps, inline SVG bars)."""
from __future__ import annotations

import html
from datetime import datetime, timezone

from .analyze import aggregate, top_sessions
from .pricing import fmt_dollars, session_cost, total_cost

CSS = """body{font-family:system-ui,sans-serif;max-width:960px;margin:2rem auto;padding:0 1rem;color:#e8e8e8;background:#141417}
h1,h2{color:#fff}.card{background:#1e1e24;border-radius:12px;padding:1rem 1.2rem;margin:1rem 0}
.bar{height:14px;border-radius:7px;background:#333}.bar>i{display:block;height:100%;border-radius:7px;background:linear-gradient(90deg,#7c6cf0,#4cc9f0)}
table{width:100%;border-collapse:collapse;font-size:.9rem}th,td{text-align:left;padding:.35rem .5rem;border-bottom:1px solid #333}
.mut{color:#999;font-size:.85rem}"""


def _bars(rows: list[tuple[str, float]]) -> str:
    denom = max((v for _, v in rows), default=1)
    out = []
    for name, val in rows:
        pct = 100 * val / (sum(v for _, v in rows) or 1)
        w = 100 * val / denom
        out.append(f"<div>{html.escape(name)} — <b>{val:,.0f}</b> ({pct:.1f}%)"
                   f"<div class=bar><i style='width:{w:.1f}%'></i></div></div>")
    return "\n".join(out)


def build_html(result, title: str = "UsageSniffer report") -> str:
    t = aggregate(result.sessions)
    tc = total_cost(result.sessions)
    by_agent: dict[str, list] = {}
    for s in result.sessions:
        by_agent.setdefault(s.agent, []).append(s)
    agent_rows = "".join(
        f"<tr><td>{html.escape(a)}</td><td>{len(ss)}</td>"
        f"<td>{sum(s.total_tokens for s in ss):,.0f}</td>"
        f"<td>{fmt_dollars(total_cost(ss)['total'])}</td></tr>"
        for a, ss in sorted(by_agent.items()))
    sess_rows = "".join(
        f"<tr><td>{html.escape(s.agent)}</td><td>{html.escape(s.session_id[:16])}</td>"
        f"<td>{html.escape(s.model[:24])}</td><td>{s.total_tokens:,.0f}</td>"
        f"<td>{fmt_dollars(session_cost(s)['total'])}</td></tr>"
        for s in top_sessions(result.sessions, 25))
    bucket_rows = [(k, float(v)) for k, v in t.buckets.most_common()]
    action = [(k, float(v)) for k, v in t.buckets.items() if k != "context_cache"]
    action.sort(key=lambda kv: -kv[1])
    from .doctor import run_all as _doctor
    try:
        findings = _doctor(result.sessions)[:20]
    except Exception:
        findings = []
    if findings:
        doc_rows = "".join(
            f"<tr><td>{html.escape(f['check'])}</td><td>{html.escape(f['severity'])}</td>"
            f"<td>{html.escape(f['detail'])}</td><td>{html.escape(f['fix'])}</td></tr>"
            for f in findings)
        doc = (f"<div class=card><h2>Doctor findings ({len(findings)} shown)</h2><table>"
               f"<tr><th>Check</th><th>Severity</th><th>Finding</th><th>Suggested fix</th></tr>"
               f"{doc_rows}</table></div>")
    else:
        doc = "<div class=card><h2>Doctor findings</h2><p class=mut>Nothing worth flagging.</p></div>"
    return f"""<!DOCTYPE html><html><head><meta charset=utf-8><title>{html.escape(title)}</title>
<style>{CSS}</style></head><body>
<h1>UsageSniffer report</h1>
<p class=mut>Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC} · {t.sessions} sessions ·
{sum(s.total_tokens for s in result.sessions):,.0f} tokens · est. {fmt_dollars(tc['total'])}
(cache saved ~{fmt_dollars(tc['saved_by_cache'])})</p>
<div class=card><h2>By agent</h2><table>
<tr><th>Agent</th><th>Sessions</th><th>Tokens</th><th>Est. cost</th></tr>{agent_rows}</table></div>
<div class=card><h2>Attribution buckets</h2>{_bars(bucket_rows)}</div>
<div class=card><h2>Action share (excl. context cache)</h2>{_bars(action)}</div>
{doc}
<div class=card><h2>Top sessions</h2><table>
<tr><th>Agent</th><th>Session</th><th>Model</th><th>Tokens</th><th>Est. cost</th></tr>{sess_rows}</table></div>
<p class=mut>Totals from logs; buckets and costs are estimates, not billing.</p>
</body></html>"""
