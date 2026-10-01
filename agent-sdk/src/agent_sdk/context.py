"""What an agent is given besides its view: its role, randomness, the platform's rules for
messages, and model access."""
from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass

from agent_sdk.llm import LLMClient
from agent_sdk.roles import Role

LLMFactory = Callable[[str, str], LLMClient]   # (profile, stage) -> client tagged for this match


@dataclass(frozen=True)
class ProtocolInfo:
    """How the platform carries messages."""
    name: str
    structured: bool      # True: action and price travel next to the text; False: only the text is delivered
    description: str      # one line for prompts: how offers and acceptances work on this platform


@dataclass(kw_only=True)
class AgentContext:
    role: Role
    rng: random.Random                     # seeded per match and role; take any randomness from here
    protocol: ProtocolInfo
    llm_factory: LLMFactory | None = None

    def llm(self, profile: str | None, stage: str) -> LLMClient:
        """A model client for `profile`. Use one `stage` name per call site, so logs and costs split by stage."""
        if not profile:
            raise ValueError("this agent needs a model profile (spec.model)")
        if self.llm_factory is None:
            raise RuntimeError("no LLM factory in this context")
        return self.llm_factory(profile, stage)
