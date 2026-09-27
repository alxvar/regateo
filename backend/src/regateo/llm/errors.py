"""Provider-neutral errors. Callers catch these, never SDK exceptions."""
from __future__ import annotations

from regateo.core.agent import Abort


class LLMError(Exception):
    def __init__(self, message: str, *, retryable: bool = False, status: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.status = status


class LLMTimeout(LLMError):
    def __init__(self, message: str = "model call timed out"):
        super().__init__(message, retryable=True)


class LLMRateLimited(LLMError):
    def __init__(self, message: str = "rate limited", *, retry_after_s: float | None = None):
        super().__init__(message, retryable=True, status=429)
        self.retry_after_s = retry_after_s


class LLMRefusal(LLMError):
    def __init__(self, message: str = "model refused", *, category: str | None = None):
        super().__init__(message)
        self.category = category


class LLMBadOutput(LLMError):
    """The model answered, but not in the requested shape (schema mismatch, truncated JSON)."""

    def __init__(self, message: str, *, text: str = ""):
        super().__init__(message)
        self.text = text


class BudgetExceeded(Abort):
    """Not an LLMError on purpose: agents fall back on LLMError and keep playing, but a spent
    budget must stop the match and the run."""
