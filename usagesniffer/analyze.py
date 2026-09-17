"""Aggregation + heuristics shared by the CLI renderer."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .models import ScanResult

COST_PER_MTOK = {  # rough blended defaults, override with --price flags later
    "claude": {"input": 3.0, "output": 15.0},
    "codex": {"input": 2.5, "output": 10.0},
    "opencode": {"input": 1.5, "output": 6.0},
}


@dataclass
class Totals:
    sessions: int = 0
    messages: int = 0
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    reasoning: int = 0
    buckets: Counter = None  # type: ignore
    tools: Counter = None  # type: ignore
    skills: Counter = None  # type: ignore

    def __post_init__(self):
        self.buckets = self.buckets or Counter()
        self.tools = self.tools or Counter()
        self.skills = self.skills or Counter()

    @property
    def grand(self) -> int:
        return self.input + self.output + self.cache_read + self.cache_write


def aggregate(sessions) -> Totals:
    t = Totals()
    for s in sessions:
        t.sessions += 1
        t.messages += s.n_messages
        t.input += s.input_tokens
        t.output += s.output_tokens
        t.cache_read += s.cache_read
        t.cache_write += s.cache_write
        t.reasoning += s.reasoning_tokens
        t.buckets.update({k: int(v) for k, v in s.buckets.items()})
        t.tools.update(s.tools)
        t.skills.update(s.skills)
    return t


def top_sessions(sessions, n=10):
    return sorted(sessions, key=lambda s: s.total_tokens, reverse=True)[:n]
