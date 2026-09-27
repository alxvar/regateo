"""Turn a deal (or its absence) into an Outcome with per-role scores."""
from __future__ import annotations

from regateo.core.outcome import EndReason, Outcome
from regateo.core.roles import Role
from regateo.core.scenario import Scenario
from regateo.referee.detect import DealEvent


def score(scenario: Scenario, event: DealEvent | None, end_reason: EndReason, *,
          messages: int, detail: str = "") -> Outcome:
    if event is None:
        if end_reason is EndReason.DEAL:
            raise ValueError("end_reason is DEAL but there is no deal event")
        return Outcome(deal=False, messages=messages, end_reason=end_reason, detail=detail)

    past = None
    if event.price < scenario.seller_reservation:
        past = Role.SELLER
    elif event.price > scenario.buyer_reservation:
        past = Role.BUYER
    return Outcome(
        deal=True,
        price=event.price,
        closed_by=event.accepted_by,
        closed_at=event.idx,
        messages=messages,
        end_reason=EndReason.DEAL,
        seller_share=scenario.surplus_share(Role.SELLER, event.price),
        buyer_share=scenario.surplus_share(Role.BUYER, event.price),
        past_reservation=past,
        detail=detail or event.evidence,
    )
