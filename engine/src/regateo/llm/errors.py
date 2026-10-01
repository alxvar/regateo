"""Provider-neutral errors. Callers catch these, never SDK exceptions. The model errors agents
catch are defined in the agent SDK."""
from __future__ import annotations

from agent_sdk.agent import Abort
from agent_sdk.llm import LLMBadOutput, LLMError, LLMRateLimited, LLMRefusal, LLMTimeout

__all__ = ["BudgetExceeded", "LLMBadOutput", "LLMError", "LLMRateLimited", "LLMRefusal", "LLMTimeout"]


class BudgetExceeded(Abort):
    """Not an LLMError on purpose: agents fall back on LLMError and keep playing, but a spent
    budget must stop the match and the run."""
