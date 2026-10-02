"""strategist v2: v1's strategist and negotiator, with clearer prompts (one turn numbering, which way is within the
walk-away price, a plan that can hold or step, how to close in the endgame) and per-turn facts for the negotiator
(messages left, their latest offer, our last offer). Code still holds only the hard limits.

Configs: guided (plan every 2 messages), guided-full (the negotiator sees the whole conversation).
"""
from __future__ import annotations

from agent_sdk import AgentConfig, AgentContext, PrivateView

from .agent import NEGOTIATOR_PROMPT, STRATEGIST_PROMPT, StrategistAgent

PARAMS = {"replan_every", "replan_on_flag", "strategist_model", "strategist_max_tokens", "window", "accept_words",
          "max_tokens"}


def build(config: AgentConfig, view: PrivateView, ctx: AgentContext) -> StrategistAgent:
    p = config.params
    if unknown := set(p) - PARAMS:
        raise ValueError(f"unknown params {sorted(unknown)}; known: {sorted(PARAMS)}")
    if int(p.get("replan_every", 2)) < 1:
        raise ValueError("replan_every must be at least 1")
    if int(p.get("window", 6)) < 0:
        raise ValueError("window must be 0 (all) or more")
    return StrategistAgent(config, view, ctx)


def prompts_in_use(params: dict) -> list[str]:
    """The prompts a config renders, for tools that show an agent's prompts."""
    return [STRATEGIST_PROMPT, NEGOTIATOR_PROMPT]
