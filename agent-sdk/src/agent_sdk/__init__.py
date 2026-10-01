"""What a negotiating agent is written against (docs/06-agent-contract.md).

An agent implements `Agent.respond(Observation) -> Move`. It is told its `PrivateView` once and
an `Observation` each turn, and reaches models only through its `AgentContext`. Nothing else
about the match, the opponent or the referee is available to it.
"""
from agent_sdk.agent import Abort, Agent, Observation
from agent_sdk.config import AgentConfig
from agent_sdk.context import AgentContext, LLMFactory, ProtocolInfo
from agent_sdk.llm import (
    ChatMessage,
    LLMBadOutput,
    LLMClient,
    LLMError,
    LLMRateLimited,
    LLMRefusal,
    LLMRequest,
    LLMResponse,
    LLMTimeout,
    Usage,
)
from agent_sdk.messages import ActionKind, Message, Move
from agent_sdk.prompts import PromptDir
from agent_sdk.roles import Role, better_or_equal, other, sign
from agent_sdk.view import PrivateView

__all__ = [
    "Abort", "ActionKind", "Agent", "AgentConfig", "AgentContext", "ChatMessage", "LLMBadOutput", "LLMClient",
    "LLMError", "LLMFactory", "LLMRateLimited", "LLMRefusal", "LLMRequest", "LLMResponse", "LLMTimeout", "Message",
    "Move", "Observation", "PrivateView", "PromptDir", "ProtocolInfo", "Role", "Usage", "better_or_equal", "other",
    "sign",
]
