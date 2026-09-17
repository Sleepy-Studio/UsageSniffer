# UsageSniffer

Scan your local **Claude Code**, **Codex**, **Opencode**, **Gemini CLI**,
**Copilot CLI**, **Cursor**, **Aider**, and **Continue** sessions and see
visually what eats your tokens — skills, thinking, tools, context cache, plus
dollar costs, anomalies, and cross-agent comparisons.

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
python3 -m usagesniffer cost --top 10        # dollar rollup + cache savings
python3 -m usagesniffer cost --budget 50     # exit 2 + alert when over $50
python3 -m usagesniffer report -o report.html
python3 -m usagesniffer watch --interval 30  # live burn (Ctrl-C to stop)
python3 -m usagesniffer anomalies            # outlier sessions vs agent baseline
python3 -m usagesniffer skills-roi           # per-skill cost table
python3 -m usagesniffer compare              # cross-agent efficiency
# filters work on most commands:
python3 -m usagesniffer scan --since 2026-09-01 --project Sunrise --model sonnet
```

## What it reads

| Agent   | Source | Ground-truth token signal |
|---------|--------|---------------------------|
| Claude  | `~/.claude/projects/*/*.jsonl` | `message.usage`: input / output / cache_creation / cache_read per assistant message |
| Codex   | `~/.codex/sessions/**/*.jsonl` | `event_msg` → `token_count`: `last_token_usage` per step (input / cached / output / reasoning) |
| Opencode| `~/.local/share/opencode/opencode.db` | `message.data.tokens` + `part` rows (text / reasoning / tool) |
| Gemini  | `~/.gemini/tmp/*/chats/*.json` | per-message `tokens` {input, output, cached, thoughts, tool} |
| Copilot | `~/.copilot/session-store.db` | `assistant_usage_events` per turn (input / output / cache / reasoning). Subscription billing → $ unknown |
| Cursor  | `~/.config/Cursor/User/**/state.vscdb` | ⚠️ per-bubble tokens read as zero on current builds; char-estimated, cost from `usageData.costInCents` when present |
| Aider   | `.aider.chat.history.md` / `--analytics-log` JSONL | real tokens only via analytics log (`prompt_tokens`, `completion_tokens`, `cost`); transcripts are char-estimated |
| Continue| `~/.continue/sessions/*.json` | session `usage` {promptTokens, completionTokens, cachedTokens} when the model reports it |

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

- [x] per-model pricing + $ cost rollup (`cost`, `--budget`)
- [x] `--watch` live mode
- [x] static HTML report export (`report`)
- [x] prompt-caching savings estimate (cache_read vs full-price replay)
- [x] 8-agent coverage (Claude, Codex, Opencode, Gemini, Copilot, Cursor, Aider, Continue)
- [x] anomalies, skill ROI, cross-agent compare
- [ ] PyPI publish (`pipx install usagesniffer`) — see `packaging.md`
- [ ] Homebrew / AUR packages — templates in `packaging.md`
