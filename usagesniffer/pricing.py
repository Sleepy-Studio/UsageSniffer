"""Model pricing ($ per million tokens) and cost rollups.

Prices are blended public-list approximations (2026 era). They drift —
treat costs as estimates, override via --price model=in,out if needed.
Cache reads are ~10% of input price on Anthropic-style billing;
cache writes ~125%. Reasoning tokens bill as output.
"""
from __future__ import annotations

# model substring -> (input $/M, output $/M)
PRICES: dict[str, tuple[float, float]] = {
    # Anthropic Claude
    "claude-opus-4": (15.0, 75.0),
    "claude-sonnet-4": (3.0, 15.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-haiku": (0.8, 4.0),
    "claude-3-5-sonnet": (3.0, 15.0),
    "claude-3-opus": (15.0, 75.0),
    # OpenAI GPT / Codex
    "gpt-5": (2.5, 10.0),
    "gpt-5-mini": (0.6, 2.4),
    "gpt-4o": (2.5, 10.0),
    "gpt-4.1": (2.0, 8.0),
    "o3": (2.0, 8.0),
    "o4-mini": (1.1, 4.4),
    # Google Gemini
    "gemini-2.5-pro": (1.25, 10.0),
    "gemini-2.5-flash": (0.3, 2.5),
    "gemini-3-pro": (2.0, 12.0),
    # xAI / others via opencode
    "grok": (2.0, 10.0),
    "mimo": (0.0, 0.0),  # free tier
    "deepseek": (0.55, 2.19),
    "qwen": (0.4, 1.6),
    "llama": (0.3, 0.6),
}

# agent fallback when no model matches: (input $/M, output $/M)
AGENT_DEFAULTS: dict[str, tuple[float, float]] = {
    "claude": (3.0, 15.0),
    "codex": (2.5, 10.0),
    "opencode": (1.5, 6.0),
    "gemini": (1.25, 10.0),
    "copilot": (0.0, 0.0),   # subscription billing — tokens tracked, $ unknown
    "cursor": (3.0, 15.0),
    "aider": (2.0, 8.0),
    "continue": (2.0, 8.0),
}

CACHE_READ_MULT = 0.10   # cache reads ~10% of input price
CACHE_WRITE_MULT = 1.25  # cache writes ~125% of input price


def rate_for(model: str, agent: str) -> tuple[float, float]:
    m = (model or "").lower()
    for key, rate in PRICES.items():
        if key in m:
            return rate
    return AGENT_DEFAULTS.get(agent, (2.0, 8.0))


def session_cost(s, rate: tuple[float, float] | None = None) -> dict:
    """Dollar estimate for one SessionRecord."""
    rate = rate or rate_for(s.model, s.agent)
    pin, pout = rate
    input_cost = s.input_tokens / 1e6 * pin
    output_cost = (s.output_tokens + s.reasoning_tokens) / 1e6 * pout
    read_cost = s.cache_read / 1e6 * pin * CACHE_READ_MULT
    write_cost = s.cache_write / 1e6 * pin * CACHE_WRITE_MULT
    total = input_cost + output_cost + read_cost + write_cost
    # What cache reads would have cost at full input price (the savings).
    uncached = s.cache_read / 1e6 * pin
    return {
        "input": input_cost, "output": output_cost,
        "cache_read": read_cost, "cache_write": write_cost,
        "total": total, "saved_by_cache": max(0.0, uncached - read_cost),
    }


def total_cost(sessions) -> dict:
    agg = {"input": 0.0, "output": 0.0, "cache_read": 0.0,
           "cache_write": 0.0, "total": 0.0, "saved_by_cache": 0.0}
    for s in sessions:
        c = session_cost(s)
        for k in agg:
            agg[k] += c[k]
    return agg


def fmt_dollars(d: float) -> str:
    if d >= 1000:
        return f"${d:,.0f}"
    if d >= 10:
        return f"${d:,.2f}"
    return f"${d:.2f}"
