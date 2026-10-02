"""What the model decides each turn: the structured output of the one call."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Decision(BaseModel):
    action: Literal["offer", "accept", "reject", "message", "walk_away"]
    price: float | None = Field(default=None, description="price offered or accepted; null otherwise")
    message: str = Field(description="what the other side reads")


class AnalysisFirst(BaseModel):
    """What the model fills in with `analysis` on: private reasoning first, so the price follows from it."""
    analysis: str = Field(description="private notes; the other side never sees them")
    action: Literal["offer", "accept", "reject", "message", "walk_away"]
    price: float | None = Field(default=None, description="price offered or accepted; null otherwise")
    message: str = Field(description="what the other side reads")


class AnalysedDecision(Decision):
    """A decision with the analysis behind it. The analysis is kept in the move's meta, and left out
    when the conversation is replayed to the model, like any other private note."""
    analysis: str
