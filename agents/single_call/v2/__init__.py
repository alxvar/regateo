"""single_call v2: v1 plus a prompt that keeps their prices out of our messages (v4) and a `attempts` param.

Configs: no-quote (prompt v4, otherwise the baseline) and retry3 (the baseline with three attempts before repair).
"""
from __future__ import annotations

from agent_sdk import AgentConfig, AgentContext, PrivateView

from .agent import DEFAULT_PROMPT, SingleCallAgent, _analysis_ref
from .vetoes import ACCEPT_WORDS, CHECKS


def build(config: AgentConfig, view: PrivateView, ctx: AgentContext) -> SingleCallAgent:
    if config.params.get("checks") not in (None, *CHECKS):
        raise ValueError(f"unknown checks {config.params['checks']!r}; known: {CHECKS}")
    if config.params.get("accept_words") not in (None, *ACCEPT_WORDS):
        raise ValueError(f"unknown accept_words {config.params['accept_words']!r}; known: {ACCEPT_WORDS}")
    if not 1 <= int(config.params.get("attempts", 2)) <= 5:
        raise ValueError("attempts must be between 1 and 5")
    return SingleCallAgent(config, view, ctx)


def prompts_in_use(params: dict) -> list[str]:
    """The prompts a config renders, for tools that show an agent's prompts (the climb loop)."""
    return [params.get("prompt", DEFAULT_PROMPT), *filter(None, [_analysis_ref(params)])]
