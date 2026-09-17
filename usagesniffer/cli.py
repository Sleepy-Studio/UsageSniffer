"""CLI: scan | top | session | cost | report | watch | anomalies | skills-roi | compare"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .models import ScanResult
from .parsers import aider as p_aider
from .parsers import claude as p_claude
from .parsers import codex as p_codex
from .parsers import continue_ as p_continue
from .parsers import copilot as p_copilot
from .parsers import cursor as p_cursor
from .parsers import gemini as p_gemini
from .parsers import opencode as p_opencode
from .render import render_overview, render_session

ALL_AGENTS = ("claude", "codex", "opencode", "gemini", "copilot", "cursor", "aider", "continue")

_PARSERS = {
    "claude": p_claude.scan, "codex": p_codex.scan, "opencode": p_opencode.scan,
    "gemini": p_gemini.scan, "copilot": p_copilot.scan, "cursor": p_cursor.scan,
    "aider": p_aider.scan, "continue": p_continue.scan,
}


def do_scan(agents=ALL_AGENTS, limit=0) -> ScanResult:
    sessions = []
    for a in agents:
        fn = _PARSERS.get(a)
        if fn:
            try:
                sessions += fn()
            except Exception:
                continue
    if limit and len(sessions) > limit:
        sessions = sorted(sessions, key=lambda s: s.total_tokens, reverse=True)[:limit]
    return ScanResult(sessions)


def apply_filters(sessions, since="", project="", model=""):
    out = sessions
    if since:
        try:
            cutoff = datetime.fromisoformat(since).replace(tzinfo=timezone.utc).timestamp()
            out = [s for s in out if not s.started or s.started >= cutoff]
        except ValueError:
            print(f"warning: ignoring bad --since {since!r} (use YYYY-MM-DD)", file=sys.stderr)
    if project:
        out = [s for s in out if project.lower() in (s.project + s.cwd).lower()]
    if model:
        out = [s for s in out if model.lower() in s.model.lower()]
    return out


def add_common(p):
    p.add_argument("--agents", default=None, help=f"comma list (default: all): {','.join(ALL_AGENTS)}")
    p.add_argument("--since", default="", help="only sessions started on/after YYYY-MM-DD (unknown dates kept)")
    p.add_argument("--project", default="", help="substring filter on project/cwd")
    p.add_argument("--model", default="", help="substring filter on model")
    p.add_argument("--limit", type=int, default=0, help="cap sessions parsed (heaviest kept)")


def resolve_agents(args) -> tuple:
    raw = args.agents or ",".join(ALL_AGENTS)
    agents = tuple(a.strip() for a in raw.split(",") if a.strip())
    bad = [a for a in agents if a not in ALL_AGENTS]
    if bad:
        print(f"warning: unknown agents ignored: {','.join(bad)}", file=sys.stderr)
    return tuple(a for a in agents if a in ALL_AGENTS) or ALL_AGENTS


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="usagesniffer", description="Visualize AI-agent token usage")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_scan = sub.add_parser("scan", help="scan all sessions and print overview")
    p_scan.add_argument("--top", type=int, default=10)
    add_common(p_scan)

    p_top = sub.add_parser("top", help="alias for scan --top N")
    p_top.add_argument("--top", type=int, default=15)
    add_common(p_top)

    p_sess = sub.add_parser("session", help="drill into one session id (prefix match)")
    p_sess.add_argument("sid")
    add_common(p_sess)

    p_cost = sub.add_parser("cost", help="dollar-cost rollup with cache savings and budget check")
    p_cost.add_argument("--top", type=int, default=15)
    p_cost.add_argument("--budget", type=float, default=0.0, help="alert if total exceeds $BUDGET")
    add_common(p_cost)

    p_rep = sub.add_parser("report", help="write self-contained HTML report")
    p_rep.add_argument("-o", "--out", default="usagesniffer-report.html")
    add_common(p_rep)

    p_watch = sub.add_parser("watch", help="live token burn (rescans on interval)")
    p_watch.add_argument("--interval", type=int, default=30, help="seconds between rescans")
    p_watch.add_argument("--rounds", type=int, default=0, help="0 = forever")
    add_common(p_watch)

    p_anom = sub.add_parser("anomalies", help="flag sessions deviating from agent baselines")
    add_common(p_anom)

    p_roi = sub.add_parser("skills-roi", help="per-skill session cost table")
    add_common(p_roi)

    p_cmp = sub.add_parser("compare", help="cross-agent efficiency comparison")
    add_common(p_cmp)

    args = ap.parse_args(argv)
    agents = resolve_agents(args)

    if args.cmd == "report":
        from .report import build_html
        res = do_scan(agents, getattr(args, "limit", 0))
        res.sessions = apply_filters(res.sessions, args.since, args.project, args.model)
        Path(args.out).write_text(build_html(res), encoding="utf-8")
        print(f"wrote {args.out} ({len(res.sessions)} sessions)")
        return 0

    if args.cmd == "watch":
        from .analyze import aggregate
        from .pricing import fmt_dollars, total_cost
        rnd = 0
        try:
            while True:
                rnd += 1
                res = do_scan(agents)
                res.sessions = apply_filters(res.sessions, args.since, args.project, args.model)
                t = aggregate(res.sessions)
                tc = total_cost(res.sessions)
                now = datetime.now(timezone.utc).strftime("%H:%M:%S")
                print(f"[{now}] sessions={t.sessions} tokens={t.grand:,} est={fmt_dollars(tc['total'])} "
                      f"(round {rnd})", flush=True)
                if args.rounds and rnd >= args.rounds:
                    break
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("(stopped)")
        return 0

    if args.cmd == "anomalies":
        from .insights import detect_anomalies
        res = do_scan(agents, getattr(args, "limit", 0))
        res.sessions = apply_filters(res.sessions, args.since, args.project, args.model)
        findings = detect_anomalies(res.sessions)
        if not findings:
            print("No anomalies (need 3+ sessions per agent for a baseline).")
            return 0
        for f in findings[:30]:
            if f["bucket"] == "tool-count":
                print(f"  [{f['agent']}] {f['session'][:24]} tool calls x{f['tokens']} "
                      f"({f['ratio']:.1f}x agent median)")
            else:
                print(f"  [{f['agent']}] {f['session'][:24]} {f['bucket']} "
                      f"{f['share']*100:.1f}% vs {f['baseline']*100:.1f}% baseline "
                      f"({f['ratio']:.1f}x, ~{f['tokens']:,} tok)")
        return 0

    if args.cmd == "skills-roi":
        from .insights import skill_roi
        from .pricing import fmt_dollars
        res = do_scan(agents, getattr(args, "limit", 0))
        res.sessions = apply_filters(res.sessions, args.since, args.project, args.model)
        rows = skill_roi(res.sessions)
        if not rows:
            print("No skill usage detected.")
            return 0
        print(f"  {'skill':<36} {'sess':>5} {'median $':>10} {'total $':>10}")
        for r in rows[:25]:
            print(f"  {r['skill'][:36]:<36} {r['sessions']:>5} "
                  f"{fmt_dollars(r['median_cost']):>10} {fmt_dollars(r['total_cost']):>10}")
        return 0

    if args.cmd == "compare":
        from .insights import compare_agents
        from .pricing import fmt_dollars
        res = do_scan(agents, getattr(args, "limit", 0))
        res.sessions = apply_filters(res.sessions, args.since, args.project, args.model)
        for r in compare_agents(res.sessions):
            print(f"  {r['agent']:<9} sessions={r['sessions']:<4} msgs={r['messages']:<6} "
                  f"total={fmt_dollars(r['total_cost']):>9} $/msg={fmt_dollars(r['cost_per_msg']):>7} "
                  f"think={r['thinking_share']*100:5.1f}% tools/msg={r['tools_per_msg']:.1f}")
        return 0

    if args.cmd == "cost":
        from .analyze import aggregate
        from .pricing import fmt_dollars, session_cost, total_cost
        res = do_scan(agents, getattr(args, "limit", 0))
        res.sessions = apply_filters(res.sessions, args.since, args.project, args.model)
        if not res.sessions:
            print("No sessions found.")
            return 1
        tc = total_cost(res.sessions)
        print(f"sessions: {len(res.sessions)}   est. total: {fmt_dollars(tc['total'])}   "
              f"cache saved: ~{fmt_dollars(tc['saved_by_cache'])}")
        print(f"  input {fmt_dollars(tc['input'])}  output {fmt_dollars(tc['output'])}  "
              f"cache_read {fmt_dollars(tc['cache_read'])}  cache_write {fmt_dollars(tc['cache_write'])}")
        print(f"--- top {args.top} sessions by cost ---")
        ranked = sorted(res.sessions, key=lambda s: session_cost(s)["total"], reverse=True)[:args.top]
        for s in ranked:
            c = session_cost(s)
            print(f"  [{s.agent}] {s.session_id[:24]:<24} {fmt_dollars(c['total']):>9}  {s.model[:28]}")
        if args.budget and tc["total"] > args.budget:
            print(f"OVER BUDGET: {fmt_dollars(tc['total'])} > {fmt_dollars(args.budget)}")
            return 2
        if args.budget:
            print(f"within budget ({fmt_dollars(tc['total'])} / {fmt_dollars(args.budget)})")
        _ = aggregate
        return 0

    # scan | top | session
    res = do_scan(agents, getattr(args, "limit", 0))
    res.sessions = apply_filters(res.sessions, getattr(args, "since", ""),
                                 getattr(args, "project", ""), getattr(args, "model", ""))
    if not res.sessions:
        print("No sessions found. Checked all known agent stores.")
        return 1
    if args.cmd == "session":
        hits = [s for s in res.sessions if s.session_id.startswith(args.sid)]
        if not hits:
            print(f"No session matching {args.sid!r}")
            return 1
        for s in hits[:5]:
            print(render_session(s))
            print()
        return 0
    print(render_overview(res, show=args.top))
    return 0


if __name__ == "__main__":
    sys.exit(main())
