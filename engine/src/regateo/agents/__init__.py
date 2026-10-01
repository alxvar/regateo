"""Building agents from specs: agent versions under agents/ and the engine's own kinds.

Importing this package registers the engine's kinds (regateo.opponents). Build an agent with
`build_agent(AgentSpec.resolve(...), view, ctx)`.
"""
from agent_sdk import AgentContext

from regateo import opponents  # noqa: E402, F401, I001  (registers the engine's kinds; imports AgentSpec)
from regateo.agents.base import AgentSpec, TrustedContext, build_agent, known_kinds, register

__all__ = ["AgentContext", "AgentSpec", "TrustedContext", "build_agent", "known_kinds", "register"]
