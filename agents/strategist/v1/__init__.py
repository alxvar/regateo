"""strategist v1: every few turns a strategist with room to think (Qwen with thinking) writes a plan: its read
of the other side, a target, the next offers, when to accept, arguments and red flags. Every turn a negotiator
(plain Qwen) follows it, seeing the plan and the recent conversation, and can flag that the plan no longer fits.
Code vetoes the hard limits (docs/02 O5).

Configs: k2 (plan every 2 messages), k1, k3, k2-fast (the strategist without thinking).
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
