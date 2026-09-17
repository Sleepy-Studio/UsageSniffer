# UsageSniffer

[![PyPI](https://img.shields.io/pypi/v/usagesniffer)](https://pypi.org/project/usagesniffer/)
[![CI](https://github.com/Sleepy-Studio/UsageSniffer/actions/workflows/ci.yml/badge.svg)](https://github.com/Sleepy-Studio/UsageSniffer/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

Scan your local **Claude Code**, **Codex**, **Opencode**, **Gemini CLI**,
**Copilot CLI**, **Cursor**, **Aider**, and **Continue** sessions and see
visually what eats your tokens — skills, thinking, tools, context cache, plus
dollar costs, anomalies, and cross-agent comparisons.

Zero-dependency Python. Your session logs never leave the machine.

## Install

Requires Python 3.10+.

```bash
# install from PyPI (recommended)
pipx install usagesniffer
usagesniffer scan --top 10

# or run straight from a repo checkout (no install needed)
python3 -m usagesniffer scan --top 10
```

## Quick start

```bash
usagesniffer scan --top 10                     # everything
usagesniffer scan --agents claude --top 5
usagesniffer session 05062c81                  # drill into one session (prefix match)
usagesniffer cost --top 10                     # dollar rollup + cache savings
usagesniffer cost --budget 50                  # exit 2 + alert when over $50
usagesniffer report -o report.html
usagesniffer watch --interval 30               # live burn (Ctrl-C to stop)
usagesniffer anomalies                         # outlier sessions vs agent baseline
usagesniffer skills-roi                        # per-skill cost table
usagesniffer compare                           # cross-agent efficiency
# filters work on most commands:
usagesniffer scan --since 2026-09-01 --project Sunrise --model sonnet
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
  pricing.py           # per-model $/Mtok rates + cost rollups
  insights.py          # anomalies, skill ROI, cross-agent compare
  render.py            # terminal ASCII charts (stdlib only)
  report.py            # self-contained HTML report
  cli.py               # scan | top | session | cost | report | watch |
                       #   anomalies | skills-roi | compare
  parsers/
    claude.py codex.py opencode.py gemini.py
    copilot.py cursor.py aider.py continue_.py
tests/
  smoke_fixtures.py    # synthetic sessions through the real pipeline
```

## Roadmap

- [x] per-model pricing + $ cost rollup (`cost`, `--budget`)
- [x] `--watch` live mode
- [x] static HTML report export (`report`)
- [x] prompt-caching savings estimate (cache_read vs full-price replay)
- [x] 8-agent coverage (Claude, Codex, Opencode, Gemini, Copilot, Cursor, Aider, Continue)
- [x] anomalies, skill ROI, cross-agent compare
- [x] PyPI publish (`pipx install usagesniffer`)
- [ ] Homebrew / AUR packages — templates in `packaging.md`
