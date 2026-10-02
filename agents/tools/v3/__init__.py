"""tools v3 (v2 plus: an acceptance is checked at the price its message names, which must be within the limit
and be in the message, instead of being vetoed whenever their message names any amount past our limit; and the
optional `standing` and `horizon` settings). v2 is v1 plus: our offers read reliably for the fallback, a model
error retried once, and the optional `endgame` and `sanitize` settings. The model decides and may first call
advisor tools (docs/02 O3): offer history, an estimate of their limit, a concession schedule, a deadline belief,
an offer check and market facts. Hard limits and agreement words are vetoed in code.

Configs: call (v1's call on v3's code), standing (plus the standing-offer check), horizon (plus a note on where
the match stands, for known and unknown message limits).
"""
from __future__ import annotations

from agent_sdk import AgentConfig, AgentContext, PrivateView

from .agent import DEFAULT_PROMPT, TOOL_MODES, ToolsAgent, tools_ref

PARAMS = {"tool_mode", "tool_rounds", "assumed_rounds", "schedule_beta", "prompt", "accept_words", "max_tokens",
          "endgame", "sanitize", "standing", "horizon"}


def build(config: AgentConfig, view: PrivateView, ctx: AgentContext) -> ToolsAgent:
    p = config.params
    if unknown := set(p) - PARAMS:
        raise ValueError(f"unknown params {sorted(unknown)}; known: {sorted(PARAMS)}")
    if p.get("tool_mode", "call") not in TOOL_MODES:
        raise ValueError(f"unknown tool_mode {p['tool_mode']!r}; known: {TOOL_MODES}")
    if int(p.get("tool_rounds", 1)) < 1:
        raise ValueError("tool_rounds must be at least 1")
    if not 0 < float(p.get("schedule_beta", 0.4)):
        raise ValueError("schedule_beta must be positive")
    if (h := p.get("horizon")) is not None and not (
            isinstance(h, list | tuple) and len(h) == 2 and 1 <= int(h[0]) <= int(h[1])):
        raise ValueError(f"horizon must be [low, high] with 1 <= low <= high, got {h!r}")
    return ToolsAgent(config, view, ctx)


def prompts_in_use(params: dict) -> list[str]:
    """The prompts a config renders, for tools that show an agent's prompts."""
    return [params.get("prompt", DEFAULT_PROMPT), *filter(None, [tools_ref(params)])]
