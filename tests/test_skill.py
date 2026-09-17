"""Skill conformance test: every command/flag documented in
skills/usagesniffer/SKILL.md must exist and run with an expected exit code.

Commands that need data accept exit 1 (no sessions); cost --budget accepts 2.
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "usagesniffer" / "SKILL.md"
BIN = [sys.executable, "-m", "usagesniffer"]

# command -> acceptable exit codes
CASES = {
    "scan --top 2": (0, 1),
    "cost --top 2": (0, 1),
    "cost --budget 50": (0, 1, 2),
    "anomalies": (0, 1),
    "skills-roi": (0, 1),
    "compare": (0, 1),
    "doctor": (0, 1),
    "top --top 2": (0, 1),
}

FLAGS = ["--agents", "--since", "--project", "--model",
         "--opencode-db", "--cursor-dir", "--aider-path"]


def main() -> None:
    text = SKILL.read_text()
    m = re.match(r"^---\n(.*?)\n---", text, re.S)
    assert m and "name: usagesniffer" in m.group(1), "skill frontmatter bad"
    for trigger in ("token usage", "cost", "budget", "doctor"):
        assert trigger in m.group(1), f"trigger missing from description: {trigger}"
    print("frontmatter + triggers OK")

    # every documented subcommand exists
    help_out = subprocess.run([*BIN, "--help"], capture_output=True, text=True).stdout
    for cmd in ("scan", "top", "session", "cost", "report", "watch",
                "anomalies", "skills-roi", "compare", "doctor"):
        assert cmd in help_out, f"subcommand missing: {cmd}"
    print("subcommands OK")

    # every documented flag is accepted
    scan_help = subprocess.run([*BIN, "scan", "--help"], capture_output=True, text=True).stdout
    for flag in FLAGS:
        assert flag in scan_help, f"flag missing: {flag}"
    print("flags OK")

    # run the documented commands
    with tempfile.TemporaryDirectory() as tmp:
        for cmd, ok in CASES.items():
            args = cmd.split()
            if "--budget" in args:
                pass  # any budget exercises the gate
            r = subprocess.run([*BIN, *args], capture_output=True, text=True, timeout=300)
            assert r.returncode in ok, f"{cmd}: exit {r.returncode}\n{r.stderr[:500]}"
            print(f"run OK: {cmd} (exit {r.returncode})")
        r = subprocess.run([*BIN, "report", "-o", f"{tmp}/r.html"],
                           capture_output=True, text=True, timeout=300)
        assert r.returncode in (0, 1), r.stderr[:500]
        r = subprocess.run([*BIN, "watch", "--interval", "1", "--rounds", "1"],
                           capture_output=True, text=True, timeout=120)
        assert r.returncode in (0, 1), r.stderr[:500]
        print("run OK: report + watch")
    print("ALL SKILL TESTS PASSED")


if __name__ == "__main__":
    main()
