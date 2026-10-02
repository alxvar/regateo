"""ranged v3: v2 plus an opt-in veto on offers worse for us than the other side's standing offer (param
`standing`, default false: v3 then behaves as v2).

v2 is v1 plus a strategist that is shown a ledger of both sides' offers and told to tie each concession to the
other side's movement (param `hold`, default true; `hold: false` is v1's strategist), and a negotiator told not
to quote their prices.

Configs: hold-standing (v2's hold with the veto on; ranged/v2/hold is the same agent with it off).
"""
from __future__ import annotations

from agent_sdk import AgentConfig, AgentContext, PrivateView

from .agent import NEGOTIATOR_PROMPTS, STRATEGIST_PROMPTS, WIDTHS, RangedAgent

PARAMS = {"width", "hold", "negotiator_sees_limit", "strategist_model", "accept_words", "standing", "max_tokens"}


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
    return [STRATEGIST_PROMPTS[bool(params.get("hold", True))],
            NEGOTIATOR_PROMPTS[bool(params.get("negotiator_sees_limit", False))]]
