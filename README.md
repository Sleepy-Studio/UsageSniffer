# UsageSniffer

[![PyPI](https://img.shields.io/pypi/v/usagesniffer)](https://pypi.org/project/usagesniffer/)
[![CI](https://github.com/Sleepy-Studio/UsageSniffer/actions/workflows/ci.yml/badge.svg)](https://github.com/Sleepy-Studio/UsageSniffer/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

Scan your local **Claude Code**, **Codex**, **Opencode**, **Gemini CLI**,
**Grok Build**, **Copilot CLI**, **Cursor**, **Aider**, **Continue**, and **Hermes**
sessions and see
visually what eats your tokens — skills, thinking, tools, context cache, plus
dollar costs, anomalies, and cross-agent comparisons.

Zero-dependency Python. Your session logs never leave the machine.

## Install

Requires Python 3.10+.

**Windows (PowerShell):**

```powershell
winget install Python.Python.3.12
pip install usagesniffer        # or: pipx install usagesniffer
usagesniffer scan --top 10
```

**macOS:**

```bash
brew install python pipx
pipx install usagesniffer
usagesniffer scan --top 10
```

**Linux:**

```bash
pipx install usagesniffer        # or: pip install usagesniffer
usagesniffer scan --top 10
```

Or run from a checkout with no install: `python3 -m usagesniffer scan --top 10`.

### OS notes

- **Windows:** Claude (`%USERPROFILE%\.claude`), Codex (`%USERPROFILE%\.codex`),
  Opencode (`%USERPROFILE%\.local\share\opencode\opencode.db`), Gemini,
  Copilot, and Continue resolve automatically. Cursor is read from
   `%APPDATA%\Cursor\User`. If your stores live elsewhere:
    `usagesniffer scan --opencode-db PATH --cursor-dir DIR --aider-path FILE --hermes-db PATH --grok-home DIR`
    (Opencode also honors the `OPENCODE_DB` env var; Hermes honors `HERMES_DB`; Grok honors `GROK_HOME`).
- **macOS:** Cursor is read from `~/Library/Application Support/Cursor/User`;
  everything else is home-relative and just works.
- **Linux:** default paths as listed in "What it reads" below.

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
usagesniffer doctor                            # proactive waste audit (read-only, with fixes)
usagesniffer burn --last 14d                   # per-day token/cost trend
usagesniffer export -o snap.json               # machine-readable dump
usagesniffer prices                            # price-table source/age + overrides
usagesniffer mcp                               # MCP stdio server for agents
# filters work on most commands:
usagesniffer scan --since 2026-09-01 --project Sunrise --model sonnet
```

## What it reads

| Agent   | Source | Ground-truth token signal |
|---------|--------|---------------------------|
| Claude  | `~/.claude/projects/*/*.jsonl` | `message.usage`: input / output / cache_creation / cache_read per assistant message |
| Codex   | `~/.codex/sessions/**/*.jsonl` | `event_msg` → `token_count`: `last_token_usage` per step (input / cached / output / reasoning) |
| Opencode| `~/.local/share/opencode/opencode.db` | `message.data.tokens` + `part` rows (text / reasoning / tool) |
| Gemini  | `~/.gemini/tmp/*/chats/*.jsonl` (+ legacy `*.json`) | per-message `tokens` {input, output, cached, thoughts, tool}; subagent chats nested |
| Grok    | `~/.grok/sessions/*/*/ ` (`$GROK_HOME`) | per-turn `turn_completed` usage {inputTokens, outputTokens, cachedReadTokens, reasoningTokens} summed; `chat_history.jsonl` fallback when absent |
| Copilot | `~/.copilot/session-store.db` | `assistant_usage_events` per turn (input / output / cache / reasoning). Subscription billing → $ unknown |
| Cursor  | `~/.config/Cursor/User/**/state.vscdb` | ⚠️ per-bubble tokens read as zero on current builds; char-estimated, cost from `usageData.costInCents` when present |
| Aider   | `.aider.chat.history.md` / `--analytics-log` JSONL | real tokens only via analytics log (`prompt_tokens`, `completion_tokens`, `cost`); transcripts are char-estimated |
| Continue| `~/.continue/sessions/*.json` | session `usage` {promptTokens, completionTokens, cachedTokens} when the model reports it |
| Hermes  | `~/.hermes/state.db` (SQLite) | `sessions` input / output / cache_read / cache_write / reasoning per session; tool counts from `messages` |

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

## Agent skill

`skills/usagesniffer/SKILL.md` lets agentic CLIs (Claude Code, Codex,
Opencode) invoke UsageSniffer themselves — token questions, budget checks,
post-session post-mortems. Symlink or copy it into your skills directory:

```bash
ln -s $PWD/skills/usagesniffer ~/.agents/skills/usagesniffer
```

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
    claude.py codex.py opencode.py gemini.py grok.py
    copilot.py cursor.py aider.py continue_.py hermes.py
tests/
  smoke_fixtures.py    # synthetic sessions through the real pipeline
```

## Roadmap

- [x] per-model pricing + $ cost rollup (`cost`, `--budget`)
- [x] `--watch` live mode
- [x] static HTML report export (`report`)
- [x] prompt-caching savings estimate (cache_read vs full-price replay)
- [x] 10-agent coverage (Claude, Codex, Opencode, Gemini, Grok, Copilot, Cursor, Aider, Continue, Hermes)
- [x] anomalies, skill ROI, cross-agent compare
- [x] proactive `doctor` audit (skill weight, output hogs, model fit, cache reuse, disk)
- [x] `export --json`, `burn` trends, zero-dep MCP server, doctor in HTML reports
- [x] refreshable price table (`prices`, `~/.config/usagesniffer/prices.json` overrides)
- [ ] Homebrew / AUR packages — real formula + PKGBUILD in `packaging/` (run
  `packaging/fetch-sha.sh <ver>` after tagging, then publish to a tap / AUR)
- [x] PyPI publish (`pipx install usagesniffer`)
- [ ] Homebrew / AUR packages — templates in `packaging.md`
