"""tools v1: the model decides and may first call advisor tools (docs/02 O3): offer history, an estimate of
their limit, a concession schedule, a deadline belief, an offer check and market facts. Hard limits and
agreement words are vetoed in code.

Configs: call (the model asks for tools), eager (every tool is run and shown), none (no tools, the ablation).
"""
from __future__ import annotations

from agent_sdk import AgentConfig, AgentContext, PrivateView

from .agent import DEFAULT_PROMPT, TOOL_MODES, ToolsAgent, tools_ref

PARAMS = {"tool_mode", "tool_rounds", "assumed_rounds", "schedule_beta", "prompt", "accept_words", "max_tokens"}


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
    return ToolsAgent(config, view, ctx)


def prompts_in_use(params: dict) -> list[str]:
    """The prompts a config renders, for tools that show an agent's prompts."""
    return [params.get("prompt", DEFAULT_PROMPT), *filter(None, [tools_ref(params)])]
