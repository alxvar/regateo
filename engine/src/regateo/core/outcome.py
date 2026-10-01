"""How a match ended and what each side scored."""
from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from regateo.core.roles import Role


class EndReason(StrEnum):
    DEAL = "deal"
    ROUND_LIMIT = "round_limit"
    TIME_LIMIT = "time_limit"
    WALK_AWAY = "walk_away"
    ERROR = "error"


class Outcome(BaseModel):
    deal: bool
    price: float | None = None
    closed_by: Role | None = None              # the side whose acceptance closed the deal
    closed_at: int | None = None               # message idx of the closing acceptance
    messages: int = 0
    end_reason: EndReason
    seller_share: float = 0.0                  # surplus share, see Scenario.surplus_share
    buyer_share: float = 0.0
    past_reservation: Role | None = None       # set if the deal broke this side's reservation
    error_by: Role | None = None               # the side whose agent failed, for EndReason.ERROR
    detail: str = ""                           # error text, judge evidence, etc.

    def share(self, role: Role) -> float:
        return self.seller_share if role is Role.SELLER else self.buyer_share
