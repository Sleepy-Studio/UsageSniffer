"""CI smoke test: synthetic Grok + Gemini (JSONL) sessions through the real
parsers/pricing/report path. Grok totals are the SUM of per-turn
turn_completed usage; Gemini JSONL totals come from per-message tokens."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from usagesniffer import pricing
from usagesniffer.models import ScanResult
from usagesniffer.parsers import gemini, grok
from usagesniffer.report import build_html


def make_grok(d: Path) -> Path:
    home = d / "grokhome"
    sdir = home / "sessions" / "%2Fhome%2Fu%2Fproj" / "sess-abc123"
    sdir.mkdir(parents=True)
    (sdir / "summary.json").write_text(json.dumps({
        "info": {"sessionId": "sess-abc123"},
        "current_model_id": "grok-4.1",
        "created_at": "2026-09-10T10:00:00Z",
        "updated_at": "2026-09-10T10:30:00Z",
        "num_messages": 6,
        "generated_title": "fix tests",
    }))
    turns = [
        {"inputTokens": 10000, "outputTokens": 500, "cachedReadTokens": 8000,
         "cacheCreationTokens": 0, "reasoningTokens": 200, "totalTokens": 9000,
         "modelCalls": 2, "costUsdTicks": 100000000},
        {"inputTokens": 12000, "outputTokens": 700, "cachedReadTokens": 10000,
         "cacheCreationTokens": 100, "reasoningTokens": 300, "totalTokens": 11000,
         "modelCalls": 3, "costUsdTicks": 120000000},
    ]
    lines = []
    for i, u in enumerate(turns):
        lines.append(json.dumps({
            "method": "session/update",
            "_x.ai/session/update": {
                "update": {"sessionUpdate": "turn_completed", "usage": u},
                "promptId": f"turn-{i}",
            },
        }))
    lines.append(json.dumps({
        "method": "session/update",
        "_x.ai/session/update": {
            "update": {"sessionUpdate": "tool_call",
                       "title": "read_file", "name": "read_file"},
        },
    }))
    (sdir / "updates.jsonl").write_text("\n".join(lines))
    (sdir / "signals.json").write_text(json.dumps({
        "turnCount": 2, "toolCallCount": 1, "toolsUsed": ["read_file"],
        "modelsUsed": ["grok-4.1"], "primaryModelId": "grok-4.1",
        "contextTokensUsed": 11000, "contextWindowTokens": 2000000,
        "totalTokensBeforeCompaction": 0, "compactionCount": 0,
    }))
    return home


def make_gemini_jsonl(d: Path) -> Path:
    tmp = d / "gemtmp"
    chats = tmp / "projhash123" / "chats"
    chats.mkdir(parents=True)
    (tmp / "projects.json").write_text(json.dumps({"/home/u/gemproj": "projhash123"}))
    lines = [
        {"sessionId": "sess-gem-1", "projectHash": "projhash123",
         "startTime": "2026-09-11T09:00:00Z", "lastUpdated": "2026-09-11T09:05:00Z"},
        {"id": "m1", "timestamp": "2026-09-11T09:00:01Z", "type": "user",
         "content": [{"text": "explain this code"}]},
        {"id": "m2", "timestamp": "2026-09-11T09:00:05Z", "type": "gemini",
         "model": "gemini-2.5-flash", "content": [{"text": "here you go"}],
         "tokens": {"input": 2000, "output": 300, "cached": 1500,
                    "thoughts": 100, "tool": 50, "total": 2300},
         "toolCalls": [{"name": "read_file"}]},
        {"$set": {"lastUpdated": "2026-09-11T09:05:00Z"}},
    ]
    (chats / "session-2026-09-11-09-00-sessgem1.jsonl").write_text(
        "\n".join(json.dumps(l) for l in lines))
    # subagent chat nested under parent session id
    sub = chats / "sess-gem-1"
    sub.mkdir()
    sublines = [
        {"sessionId": "sub-1", "projectHash": "projhash123",
         "startTime": "2026-09-11T09:01:00Z", "lastUpdated": "2026-09-11T09:02:00Z",
         "kind": "subagent"},
        {"id": "s1", "timestamp": "2026-09-11T09:01:01Z", "type": "gemini",
         "model": "gemini-2.5-flash", "content": "sub result",
         "tokens": {"input": 500, "output": 100, "cached": 400,
                    "thoughts": 0, "tool": 0, "total": 600}},
    ]
    (sub / "sub-1.jsonl").write_text("\n".join(json.dumps(l) for l in sublines))
    return tmp


def main() -> None:
    d = Path(tempfile.mkdtemp())

    gs = grok.scan(make_grok(d))
    assert len(gs) == 1, gs
    g = gs[0]
    assert g.agent == "grok" and g.model == "grok-4.1", (g.agent, g.model)
    assert g.input_tokens == 22000, g.input_tokens
    assert g.output_tokens == 1200, g.output_tokens
    assert g.cache_read == 18000, g.cache_read
    assert g.cache_write == 100, g.cache_write
    assert g.reasoning_tokens == 500, g.reasoning_tokens
    assert g.tools["read_file"] >= 1, dict(g.tools)
    assert g.project.endswith("proj"), g.project
    gc = pricing.session_cost(g)
    assert gc["total"] > 0, gc

    ms = gemini.scan(make_gemini_jsonl(d))
    assert len(ms) == 2, [(m.session_id, m.input_tokens) for m in ms]
    main_rec = next(m for m in ms if m.session_id == "sess-gem-1")
    assert main_rec.input_tokens == 2000 and main_rec.output_tokens == 300, main_rec.to_row()
    assert main_rec.cache_read == 1500 and main_rec.reasoning_tokens == 100
    assert main_rec.tools["read_file"] == 1
    assert main_rec.project == "/home/u/gemproj", main_rec.project
    sub_rec = next(m for m in ms if m.session_id == "sub-1")
    assert sub_rec.input_tokens == 500 and sub_rec.output_tokens == 100

    html = build_html(ScanResult(gs + ms))
    assert "UsageSniffer report" in html and "grok" in html
    print("grok+gemini fixtures OK: grok=%d tok ($%.4f), gemini=%d sessions"
          % (g.total_tokens, gc["total"], len(ms)))


if __name__ == "__main__":
    main()
