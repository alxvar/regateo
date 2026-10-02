"""ranged v1: a strategist call sets each turn's price band, the negotiator picks the price inside it and writes
the message, and code holds the move to the band and the hard limits (docs/02 O4, with the band from the model
rather than from code). The negotiator doesn't see the walk-away price unless `negotiator_sees_limit`.

Configs: band (the strategist's band), w0, w10, w30 (bands of 0%, 10%, 30% of the market range around its
target), full (only the walk-away price binds), band-sees-limit.
"""
from __future__ import annotations

from agent_sdk import AgentConfig, AgentContext, PrivateView

from .agent import NEGOTIATOR_PROMPTS, STRATEGIST_PROMPT, WIDTHS, RangedAgent

PARAMS = {"width", "negotiator_sees_limit", "strategist_model", "accept_words", "max_tokens"}


def build(config: AgentConfig, view: PrivateView, ctx: AgentContext) -> RangedAgent:
    p = config.params
    if unknown := set(p) - PARAMS:
        raise ValueError(f"unknown params {sorted(unknown)}; known: {sorted(PARAMS)}")
    width = p.get("width", "strategist")
    if width not in WIDTHS and not (isinstance(width, int | float) and not isinstance(width, bool) and width >= 0):
        raise ValueError(f"unknown width {width!r}; known: {WIDTHS} or a number >= 0")
    return RangedAgent(config, view, ctx)


def prompts_in_use(params: dict) -> list[str]:
    """The prompts a config renders, for tools that show an agent's prompts."""
    return [STRATEGIST_PROMPT, NEGOTIATOR_PROMPTS[bool(params.get("negotiator_sees_limit", False))]]
