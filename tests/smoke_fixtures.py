"""CI smoke test: synthetic fixtures through the real parsers/pricing/report path."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from usagesniffer import pricing
from usagesniffer.models import ScanResult
from usagesniffer.parsers import claude
from usagesniffer.report import build_html


def main() -> None:
    d = Path(tempfile.mkdtemp())
    fx = d / "proj"
    fx.mkdir()
    rows = [
        {"type": "user", "message": {"content": "hello"}},
        {"type": "assistant", "message": {
            "model": "claude-sonnet-5",
            "content": [
                {"type": "text", "text": "hi there"},
                {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}],
            "usage": {"input_tokens": 100, "output_tokens": 50,
                      "cache_creation_input_tokens": 1000,
                      "cache_read_input_tokens": 5000}}},
    ]
    (fx / "s1.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    ss = claude.scan(d)
    assert len(ss) == 1 and ss[0].total_tokens == 6150, ss
    assert ss[0].tools["Bash"] == 1
    c = pricing.session_cost(ss[0])
    assert c["total"] > 0 and c["saved_by_cache"] > 0, c
    assert "UsageSniffer report" in build_html(ScanResult(ss))
    print("fixtures OK: %d tokens, cost %.4f" % (ss[0].total_tokens, c["total"]))


if __name__ == "__main__":
    main()
