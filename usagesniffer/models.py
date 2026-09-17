"""Shared data model. All parsers normalize into SessionRecord."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field


# Canonical attribution buckets (token-weighted where the source
# format gives real usage numbers, char-estimated otherwise).
BUCKETS = (
    "thinking",        # Claude thinking blocks / reasoning_output_tokens / opencode reasoning parts
    "skills",          # SKILL.md loads, skill instructions, skill-named tool calls
    "tools",           # tool_use + tool_result payloads, exec calls
    "context_cache",   # cache_read_input_tokens / cached_input_tokens / cache.read
    "context_write",   # cache_creation_input_tokens / cache_write
    "assistant_text",  # plain assistant text output
    "system",          # system/developer prompts, base instructions, AGENTS.md
    "user",            # literal user input
    "other",
)


@dataclass
class SessionRecord:
    session_id: str
    agent: str  # "claude" | "codex" | "opencode"
    project: str = ""
    cwd: str = ""
    model: str = ""
    n_messages: int = 0
    # Real token totals straight from the log format.
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_write: int = 0
    reasoning_tokens: int = 0
    # Attribution buckets (same unit as tokens where possible).
    buckets: dict = field(default_factory=lambda: {b: 0 for b in BUCKETS})
    tools: Counter = field(default_factory=Counter)
    skills: Counter = field(default_factory=Counter)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_read + self.cache_write

    def to_row(self) -> dict:
        return {
            "agent": self.agent,
            "session": self.session_id[:8],
            "model": self.model[:28],
            "msgs": self.n_messages,
            "input": self.input_tokens,
            "output": self.output_tokens,
            "cache_read": self.cache_read,
            "cache_write": self.cache_write,
            "reasoning": self.reasoning_tokens,
            "total": self.total_tokens,
            "project": self.project[-40:],
        }


@dataclass
class ScanResult:
    sessions: list = field(default_factory=list)

    def by_agent(self) -> dict:
        out: dict = {}
        for s in self.sessions:
            out.setdefault(s.agent, []).append(s)
        return out
