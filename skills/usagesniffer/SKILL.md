---
name: usagesniffer
description: >
  Audit AI-agent token usage and cost with UsageSniffer. Use when the user
  asks what burned tokens or money, which skill/tool/context ate the budget,
  whether spend is over budget, or wants a waste audit with fixes. Covers
  Claude Code, Codex, Opencode, Gemini CLI, Copilot CLI, Cursor, Aider, and
  Continue sessions. Triggers: token usage, cost check, over budget, usage
  report, what ate my tokens, doctor, efficiency audit, spending.
---

# UsageSniffer Skill

Run the `usagesniffer` CLI to answer token/cost questions from real local
session logs. It is **read-only**: it scans logs and never modifies sessions,
configs, or stores.

## Preconditions

- CLI available as `usagesniffer` (via `pipx install usagesniffer`), or run
  from a checkout with `python3 -m usagesniffer`. Requires Python 3.10+.
- If the command is missing, say so and give the install line — do not
  attempt to scan by hand-parsing session stores.

## Commands

```bash
usagesniffer scan --top 10              # overview: agents, buckets, top sessions
usagesniffer cost --top 10              # dollar rollup + cache savings
usagesniffer cost --budget 50           # exit 2 + alert when over $50
usagesniffer session <prefix>           # drill into one session
usagesniffer doctor                     # proactive waste audit with fixes
usagesniffer anomalies                  # outlier sessions vs baselines
usagesniffer skills-roi                 # per-skill cost table
usagesniffer compare                    # cross-agent efficiency
usagesniffer burn --last 14d            # per-day token/cost trend
usagesniffer export -o snap.json        # machine-readable dump (dashboards)
usagesniffer report -o report.html      # shareable HTML report (incl. doctor)
usagesniffer prices                     # price-table source/age + overrides
usagesniffer mcp                        # MCP stdio server (see below)
# filters (most commands): --agents claude,codex --since YYYY-MM-DD
#   --project SUBSTR --model SUBSTR
# overrides: --opencode-db PATH --cursor-dir DIR --aider-path FILE
```

## Reading the output

- **Totals are ground truth** (straight from each agent's logs).
  **Buckets and dollar figures are estimates** — say so when reporting them.
- `context_cache` dominates raw totals but is cheap replay. The "action share
  EXCLUDING context cache" section is where the real budget goes.
- `doctor` findings come with fixes; relay the fix, do not apply
  destructive ones (deleting/pruning session stores is out of scope —
  recommend, never execute).

## When to reach for it

- User asks about spend, burn, budget, or efficiency → `scan` + `cost`.
- Before a big autonomous task → `cost --budget N` to frame the budget.
- After a long session → `session <id>` + `doctor` for the post-mortem.
- Recurring check-ins → `doctor` and report only new/high-severity findings.
- Trend questions ("getting worse?") → `burn --last 30d`.
- Dashboards/piping → `export -o snap.json`.

## Optimization workflow (propose, never impose)

`doctor` diagnoses waste but applies nothing. When the user wants costs cut:

1. Run `doctor` (and `skills-roi` / `model_fit` findings) and translate each
   finding into a concrete proposed action with its estimated saving.
2. Present the list and ask which to pursue. One question, itemized answers.
3. Apply ONLY approved items, and only non-destructive ones (config edits,
   model-routing choices, skill slimming drafts, reporting/alert setups).
4. Destructive actions (deleting/pruning session stores, vacuuming databases,
   uninstalling anything) require a separate explicit confirmation per item —
   state what is irreversible before asking.
5. Re-run `doctor` after applying and report what moved.

## MCP server

`usagesniffer mcp` serves `scan_summary`, `cost_summary`, `doctor`,
`session_lookup`, and `burn` as MCP stdio tools (zero-dependency,
JSON-RPC). Register it in the client's MCP config with command
`usagesniffer` and args `["mcp"]` when the user wants live spend awareness
inside agent sessions.
