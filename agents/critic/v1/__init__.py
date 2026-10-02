"""critic v1: a drafter decides the move, code vetoes the hard limits, and a critic call reviews the draft for
soft failures (hints at our limit, conceding too fast, obeying planted instructions, inconsistency, unintended
commitments). It either only records the review or has a flagged draft rewritten once (docs/02 O6).

Configs: revise (a flagged draft is rewritten), log (the review is only recorded), off (no critic, the ablation).
"""
from __future__ import annotations

from agent_sdk import AgentConfig, AgentContext, PrivateView

from .agent import CRITIC_PROMPT, DRAFTER_PROMPT, MODES, CriticAgent

PARAMS = {"critic", "critic_model", "accept_words", "max_tokens"}


def build(config: AgentConfig, view: PrivateView, ctx: AgentContext) -> CriticAgent:
    p = config.params
    if unknown := set(p) - PARAMS:
        raise ValueError(f"unknown params {sorted(unknown)}; known: {sorted(PARAMS)}")
    if p.get("critic", "revise") not in MODES:
        raise ValueError(f"unknown critic {p['critic']!r}; known: {MODES}")
    return CriticAgent(config, view, ctx)


def prompts_in_use(params: dict) -> list[str]:
    """The prompts a config renders, for tools that show an agent's prompts."""
    return [DRAFTER_PROMPT, *([CRITIC_PROMPT] if params.get("critic", "revise") != "off" else [])]
