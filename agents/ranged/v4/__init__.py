"""ranged v4: v3 with the direction of their movement in the ledger fixed (v2 and v3 said "not toward you" when
they had moved toward us), plus two opt-in switches, both off by default: `clock`, a ledger that
also states when the negotiation ends and how close the two sides' offers are, with a strategist prompt on closing
a small gap before the messages run out; and `plain_final`, a negotiator told not to call an offer final unless it
is its last message.

v3 is v2 plus an opt-in veto on offers worse for us than the other side's standing offer (param `standing`).
v2 is v1 plus a strategist that is shown a ledger of both sides' offers and told to tie each concession to the
other side's movement (param `hold`, default true; `hold: false` is v1's strategist), and a negotiator told not
to quote their prices.

Configs: hold-standing (ranged/v3/hold-standing with the fixed ledger only), clock-standing (the same with the
clock), clock-standing-plain (clock-standing with plain_final), clock (ranged/v2/hold with the clock; not listed
for round-02).
"""
from __future__ import annotations

from agent_sdk import AgentConfig, AgentContext, PrivateView

from .agent import WIDTHS, RangedAgent, negotiator_prompt, strategist_prompt

PARAMS = {"width", "hold", "negotiator_sees_limit", "strategist_model", "accept_words", "standing", "clock",
          "plain_final", "max_tokens"}


def build(config: AgentConfig, view: PrivateView, ctx: AgentContext) -> RangedAgent:
    p = config.params
    if unknown := set(p) - PARAMS:
        raise ValueError(f"unknown params {sorted(unknown)}; known: {sorted(PARAMS)}")
    width = p.get("width", "strategist")
    if width not in WIDTHS and not (isinstance(width, int | float) and not isinstance(width, bool) and width >= 0):
        raise ValueError(f"unknown width {width!r}; known: {WIDTHS} or a number >= 0")
    if p.get("clock") and not p.get("hold", True):
        raise ValueError("clock needs hold: the clock's facts are part of the hold ledger")
    return RangedAgent(config, view, ctx)


def prompts_in_use(params: dict) -> list[str]:
    """The prompts a config renders, for tools that show an agent's prompts."""
    return [strategist_prompt(params), negotiator_prompt(params)]
