# UsageSniffer

Scan your local **Codex**, **Claude Code**, and **Opencode** sessions and see
visually what eats your tokens — skills, thinking, tools, context cache, etc.

Zero-dependency Python. Your session logs never leave the machine.

## Install

Requires Python 3.10+.

```bash
# run straight from the repo (no install needed)
python3 -m usagesniffer scan --top 10

# or install it so the `usagesniffer` command is on your PATH
pip install git+https://github.com/Sleepy-Studio/UsageSniffer.git
# or: pipx install git+https://github.com/Sleepy-Studio/UsageSniffer.git
usagesniffer scan --top 10
```

## Quick start

```bash
cd UsageSniffer
python3 -m usagesniffer scan --top 10        # everything
python3 -m usagesniffer scan --agents claude --top 5
python3 -m usagesniffer session 05062c81     # drill into one session (prefix match)
```

## What it reads

| Agent   | Source | Ground-truth token signal |
|---------|--------|---------------------------|
| Claude  | `~/.claude/projects/*/*.jsonl` | `message.usage`: input / output / cache_creation / cache_read per assistant message |
| Codex   | `~/.codex/sessions/**/*.jsonl` | `event_msg` → `token_count`: `last_token_usage` per step (input / cached / output / reasoning) |
| Opencode| `~/.local/share/opencode/opencode.db` | `message.data.tokens` + `part` rows (text / reasoning / tool) |

## Attribution buckets

Real totals always come straight from the logs. The *buckets* are
token-weighted estimates (labelled as such in output):

- `thinking` — Claude thinking blocks / Codex `reasoning_output_tokens` / Opencode reasoning parts
- `skills` — `SKILL.md` loads, skill-instruction blocks, Skill-tool calls
- `tools` — tool_use + tool_result / exec payload share
- `context_cache` / `context_write` — cache read / creation tokens
- `assistant_text`, `system`, `user`, `other`

The second chart ("action share EXCLUDING context cache") is the useful one:
cache reads dominate raw totals but are cheap; the action chart shows where
your real budget goes.

## Layout

```
usagesniffer/
  models.py            # SessionRecord / ScanResult
  analyze.py           # aggregation
  render.py            # terminal ASCII charts (stdlib only)
  cli.py               # scan | top | session
  parsers/
    claude.py          # ~/.claude/projects JSONL
    codex.py           # ~/.codex/sessions rollout JSONL
    opencode.py        # opencode.db SQLite
```

## Roadmap

- [ ] per-model pricing + $ cost rollup (`--price` flags)
- [ ] `--watch` live mode + session timeline sparkline
- [ ] static HTML report export (`report` subcommand)
- [ ] prompt-caching savings estimate (cache_read vs full-price replay)
