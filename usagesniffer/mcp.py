"""Zero-dependency MCP server over stdio (JSON-RPC 2.0).

Exposes UsageSniffer to agents as tools so they can query their own spend
mid-task and self-correct. Implements the minimal MCP surface:
initialize, notifications/initialized, ping, tools/list, tools/call.

Run: `usagesniffer mcp` then connect any MCP stdio client.
"""
from __future__ import annotations

import json
import sys

SERVER_INFO = {"name": "usagesniffer", "version": "1.4.0"}


def _scan(agents=None):
    from .cli import ALL_AGENTS, do_scan
    if not agents:
        return do_scan(ALL_AGENTS)
    if isinstance(agents, str):
        agents = [a.strip() for a in agents.split(",") if a.strip()]
    return do_scan(tuple(a for a in agents if a in ALL_AGENTS) or ALL_AGENTS)


def tool_scan_summary(args: dict) -> dict:
    from .analyze import aggregate
    from .pricing import total_cost
    res = _scan(args.get("agents"))
    t = aggregate(res.sessions)
    tc = total_cost(res.sessions)
    return {"sessions": t.sessions, "messages": t.messages,
            "total_tokens": t.grand, "est_cost": round(tc["total"], 2),
            "cache_saved": round(tc["saved_by_cache"], 2),
            "buckets": {k: int(v) for k, v in t.buckets.most_common()},
            "top_tools": dict(t.tools.most_common(10)),
            "top_skills": dict(t.skills.most_common(10))}


def tool_cost_summary(args: dict) -> dict:
    from .pricing import fmt_dollars, session_cost, total_cost
    res = _scan(args.get("agents"))
    tc = total_cost(res.sessions)
    top = sorted(res.sessions, key=lambda s: session_cost(s)["total"], reverse=True)[:10]
    budget = float(args.get("budget", 0) or 0)
    return {"est_total": round(tc["total"], 2), "cache_saved": round(tc["saved_by_cache"], 2),
            "over_budget": bool(budget and tc["total"] > budget),
            "top": [{"session": s.session_id[:12], "agent": s.agent,
                     "cost": round(session_cost(s)["total"], 2)} for s in top],
            "note": f"budget {fmt_dollars(budget)}" if budget else "no budget set"}


def tool_doctor(args: dict) -> dict:
    from .doctor import run_all
    res = _scan(args.get("agents"))
    return {"findings": run_all(res.sessions)[:25],
            "note": "read-only audit; apply fixes only with user approval"}


def tool_session(args: dict) -> dict:
    sid = str(args.get("session", ""))
    for s in _scan(args.get("agents")).sessions:
        if s.session_id.startswith(sid):
            return {"session": s.session_id, "agent": s.agent, "model": s.model,
                    "messages": s.n_messages, "total_tokens": s.total_tokens,
                    "buckets": {k: int(v) for k, v in s.buckets.items()},
                    "tools": dict(s.tools), "skills": dict(s.skills)}
    return {"error": f"no session matching {sid!r}"}


def tool_burn(args: dict) -> dict:
    from .burn import bucketize
    days = int(args.get("days", 14) or 14)
    rows, unk = bucketize(_scan(args.get("agents")).sessions, days)
    return {"days": [{"date": d, "tokens": t, "cost": round(c, 2)} for d, t, c in rows],
            "undated": unk}


TOOLS = {
    "scan_summary": ("Token/cost overview across sessions", tool_scan_summary,
                     {"agents": "optional comma list"}),
    "cost_summary": ("Dollar rollup with top sessions; optional budget gate", tool_cost_summary,
                     {"agents": "optional comma list", "budget": "optional dollar budget"}),
    "doctor": ("Proactive waste audit with fixes (read-only)", tool_doctor,
               {"agents": "optional comma list"}),
    "session_lookup": ("Drill into one session by id prefix", tool_session,
                       {"session": "id prefix (required)"}),
    "burn": ("Per-day token/cost burn for the last N days", tool_burn,
             {"days": "default 14"}),
}


def handle(msg: dict):
    mid = msg.get("id")
    method = msg.get("method", "")
    params = msg.get("params", {}) or {}

    def ok(result):
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def err(code, message):
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": code, "message": message}}

    if method == "initialize":
        return ok({"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                   "serverInfo": SERVER_INFO})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": [
            {"name": n, "description": d,
             "inputSchema": {"type": "object", "properties": {
                 k: {"type": "string"} for k in (schema or {})}}}
            for n, (d, _, schema) in TOOLS.items()]})
    if method == "tools/call":
        name = params.get("name", "")
        entry = TOOLS.get(name)
        if not entry:
            return err(-32602, f"unknown tool {name!r}")
        try:
            result = entry[1](params.get("arguments", {}) or {})
        except Exception as e:  # never crash the server on a tool error
            return err(-32603, f"{name} failed: {e}")
        return ok({"content": [{"type": "text",
                                "text": json.dumps(result, indent=1)}]})
    if method.startswith("notifications/"):
        return None  # no response to notifications
    return err(-32601, f"method not found: {method}")


def serve() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            resp = handle(msg)
        except Exception as e:
            resp = {"jsonrpc": "2.0", "id": msg.get("id"),
                    "error": {"code": -32603, "message": str(e)}}
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
    return 0
