"""single_call v1: O1 and O2 from before the agent packages (docs/02), with the strategy prompts v1–v3.

Configs: o1-qwen and o1-claude (no vetoes), o2-qwen (all of O2's original checks), baseline (prompt v2
with the limit and acceptance-word vetoes), and experiment 001's variants of the baseline.
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
    return SingleCallAgent(config, view, ctx)


def prompts_in_use(params: dict) -> list[str]:
    """The prompts a config renders, for tools that show an agent's prompts (the climb loop)."""
    return [params.get("prompt", DEFAULT_PROMPT), *filter(None, [_analysis_ref(params)])]
