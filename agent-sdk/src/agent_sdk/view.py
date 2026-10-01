"""What an agent is told about its negotiation at the start."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from agent_sdk.roles import Role


class PrivateView(BaseModel):
    """Everything one agent is told at the start. Nothing else counts as known."""
    model_config = ConfigDict(frozen=True)

    role: Role
    item: str
    currency: str
    reservation: float                         # our walk-away price
    market_low: float
    market_high: float
    max_rounds: int | None                     # None: deadline hidden
    time_limit_s: float | None
    opponent_range: tuple[float, float] | None = None
    context: str = ""                          # free-text brief, if the platform gives one
