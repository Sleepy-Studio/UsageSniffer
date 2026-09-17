"""CLI: python -m usagesniffer scan | top | session <id>"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .models import ScanResult
from .parsers import claude as p_claude
from .parsers import codex as p_codex
from .parsers import opencode as p_opencode
from .render import render_overview, render_session


def do_scan(agents=("claude", "codex", "opencode"), limit=0) -> ScanResult:
    sessions = []
    if "claude" in agents:
        sessions += p_claude.scan()
    if "codex" in agents:
        sessions += p_codex.scan()
    if "opencode" in agents:
        sessions += p_opencode.scan()
    if limit and len(sessions) > limit:
        # keep the heaviest? need totals first — cheap sort
        sessions = sorted(sessions, key=lambda s: s.total_tokens, reverse=True)[:limit]
    return ScanResult(sessions)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="usagesniffer", description="Visualize AI-agent token usage")
    ap.add_argument("--agents", default="claude,codex,opencode",
                    help="comma list: claude,codex,opencode")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_scan = sub.add_parser("scan", help="scan all sessions and print overview")
    p_scan.add_argument("--top", type=int, default=10)
    p_scan.add_argument("--limit", type=int, default=0, help="cap sessions parsed (heaviest kept)")
    p_scan.add_argument("--agents", default=None)
    p_top = sub.add_parser("top", help="alias for scan --top N")
    p_top.add_argument("--top", type=int, default=15)
    p_top.add_argument("--limit", type=int, default=0)
    p_top.add_argument("--agents", default=None)
    p_sess = sub.add_parser("session", help="drill into one session id (prefix match)")
    p_sess.add_argument("sid")
    p_sess.add_argument("--agents", default=None)
    args = ap.parse_args(argv)
    agents = tuple(a.strip() for a in (args.agents or "claude,codex,opencode").split(",") if a.strip())
    if args.cmd in ("scan", "top"):
        res = do_scan(agents, getattr(args, "limit", 0))
        if not res.sessions:
            print("No sessions found. Checked: ~/.claude/projects, ~/.codex/sessions, opencode.db")
            return 1
        print(render_overview(res, show=args.top))
        return 0
    if args.cmd == "session":
        res = do_scan(agents)
        hits = [s for s in res.sessions if s.session_id.startswith(args.sid)]
        if not hits:
            print(f"No session matching {args.sid!r}")
            return 1
        for s in hits[:5]:
            print(render_session(s))
            print()
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
