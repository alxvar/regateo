"""critic v2: v1 plus a facts line (messages left, standing offers) and prompts that pace concessions to the message
budget and treat stalling as a flaw, because v1 often ended without a deal.

Configs: close (critic revises), close_solo (the same drafter, no critic).
"""
from __future__ import annotations

from agent_sdk import AgentConfig, AgentContext, PrivateView

from .agent import CRITIC_PROMPT, DRAFTER_PROMPT, MODES, CriticAgent

PARAMS = {"critic", "critic_model", "accept_words", "max_tokens", "facts"}


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
