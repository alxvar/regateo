"""Negotiating agents built from specs.

Importing this package registers every built-in kind: o1, o2, boulware, scripted:<name>
and persona:<name>. Build one with `build_agent(AgentSpec.resolve(...), view, ctx)`.
"""
from regateo.agents import baselines, opponents  # noqa: F401  (registers builders)
from regateo.agents.base import AgentContext, AgentSpec, build_agent, known_kinds, register

__all__ = ["AgentContext", "AgentSpec", "build_agent", "known_kinds", "register"]
