"""The agent: parser -> opponent model -> strategy engine -> writer."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional

from .estimator import OpponentModel
from .language import Brief, RegexParser, TemplateWriter, fmt_price
from .scenario import PrivateView
from .strategy import StrategyEngine, StrategyParams

DEFAULT_PERSONA = (
    "Warm, calm and professional. Friendly and appreciative, but firm on numbers: "
    "briefly justify your price with value or market facts, never sound desperate, never insult."
)


@dataclass
class Turn:
    text: str        # what the other side sees
    action: str      # "offer" | "accept" | "confirm"  (structured, for the arena / logs)
    price: float


class NegotiationAgent:
    def __init__(self, view: PrivateView, params: Optional[StrategyParams] = None,
                 parser=None, writer=None, clock: Callable[[], float] = time.monotonic,
                 currency: str = "$"):
        self.view = view
        self.engine = StrategyEngine(view, params, clock)
        self.model = OpponentModel(view)
        self.parser = parser or RegexParser()
        self.writer = writer or TemplateWriter()
        self.currency = currency
        self.turn = 0
        self.last_price: Optional[float] = None
        self.log: list[dict] = []

    def respond(self, incoming: Optional[str]) -> Turn:
        tactics: list[str] = []
        if incoming is not None:
            span = self.view.market_high - self.view.market_low
            plausible = (self.view.market_low - span, self.view.market_high + span)
            parsed = self.parser.parse(incoming, self.last_price, plausible)
            tactics = parsed.tactics
            self.log.append({"turn": self.turn, "incoming": incoming, "parsed": parsed})
            if parsed.intent == "accept" and self.last_price is not None:
                # They accepted our standing offer: confirm it, don't reopen.
                return Turn(f"Confirmed at {fmt_price(self.last_price, self.currency)}. Thank you!",
                            "confirm", self.last_price)
            if parsed.intent == "offer" and parsed.price is not None:
                self.model.observe(parsed.price)

        # Their standing offer counts even if this particular message had no number in it.
        decision = self.engine.decide(self.model.last, self.turn, self.model)
        text = self.writer.write(Brief(self.view.role, self.view.item, decision.action,
                                       decision.price, decision.phase, tactics, self.currency))
        self.log.append({"turn": self.turn, "decision": decision, "text": text})
        self.turn += 1
        if decision.action == "offer":
            self.last_price = decision.price
        return Turn(text, decision.action, decision.price)
