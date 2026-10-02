"""The negotiator proposes inside a price band (docs/02 O4). A strategist call reads the conversation and sets
the band for the turn; the negotiator picks the price and writes the message; code only holds the move to the
band and the hard limits. Unlike docs/02's drawing, code never computes the band itself (docs/06 §3.3): the
band's `width` param sweeps how much of the strategist's choice the negotiator may override.

Least privilege: by default the negotiator never sees our walk-away price. The band already lies within it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from agent_sdk import (
    ActionKind,
    AgentConfig,
    AgentContext,
    ChatMessage,
    LLMError,
    LLMRequest,
    Move,
    Observation,
    PrivateView,
    PromptDir,
    sign,
)
from agent_sdk.guards import limit_problems, past_limit, reads_as_agreement
from agent_sdk.prices import find_prices
from pydantic import BaseModel, Field

from ..lib.common import (
    AGREEMENT_FEEDBACK,
    OWN_NOTE,
    TOL,
    Decision,
    brief,
    closing_price,
    money,
    safe_move,
    to_move,
    transcript,
    transcript_text,
    with_note,
)

PROMPTS = PromptDir(Path(__file__).parent / "prompts")
STRATEGIST_PROMPT = "strategist_system.v1"
NEGOTIATOR_PROMPTS = {True: "negotiator_system_limit.v1", False: "negotiator_system.v1"}
WIDTHS = ("strategist", "full")


class BandPlan(BaseModel):
    """The strategist's output: its read of the conversation, then the band for this turn."""
    read: str = Field(description="one or two sentences: what their latest message offers, claims or asks, "
                                  "and how far to trust it")
    target: float = Field(description="the price your side's next offer should be")
    best: float = Field(description="the best price for your side the negotiator may still offer this turn")
    worst: float = Field(description="the furthest the negotiator may concede this turn; an offer from them at "
                                     "least this good may be accepted")
    angle: str = Field(description="one sentence for the negotiator: what to stress or ask this turn")


@dataclass(frozen=True)
class Band:
    """The prices the negotiator may offer this turn, in price terms: from `worst` (the most we concede) to
    `best` (None: no bound on the side that favours us). `worst` is never past our walk-away price."""
    worst: float
    target: float
    best: float | None

    def allows(self, s: int, price: float) -> bool:
        return s * price >= s * self.worst - TOL and (self.best is None or s * price <= s * self.best + TOL)

    def clamp(self, s: int, price: float) -> float:
        u = max(s * price, s * self.worst)
        if self.best is not None:
            u = min(u, s * self.best)
        return round(s * u, 2)


def make_band(view: PrivateView, plan: BandPlan, width: str | float) -> Band:
    """The band the negotiator is held to, from the strategist's plan and the `width` param:
    "strategist" takes its band as set; "full" only keeps the walk-away price (O2's freedom); a number w
    allows w times the market range, centred on the strategist's target (0: offer exactly the target)."""
    s = sign(view.role)
    t = s * plan.target
    if width == "strategist":
        lo, hi = sorted((s * plan.worst, s * plan.best))
        lo, hi = min(lo, t), max(hi, t)
    elif width == "full":
        lo, hi = -math.inf, math.inf
    else:
        half = float(width) * abs(view.market_high - view.market_low) / 2
        lo, hi = t - half, t + half
    lo = max(lo, s * view.reservation)
    hi = max(hi, lo)
    t = min(max(t, lo), hi)
    return Band(worst=round(s * lo, 2), target=round(s * t, 2), best=None if math.isinf(hi) else round(s * hi, 2))


class RangedAgent:
    """Params:
    - `width`: "strategist" (default: the strategist's own band), "full" (any price within the walk-away
      price), or a number w >= 0 (w times the market range around the strategist's target; 0 makes the
      negotiator a writer).
    - `negotiator_sees_limit`: show the negotiator our walk-away price (default false).
    - `strategist_model`: model profile for the strategist (default: the config's model).
    - `accept_words` (veto agreement words when not accepting, default true), `max_tokens`."""

    def __init__(self, config: AgentConfig, view: PrivateView, ctx: AgentContext):
        self.name = config.name
        self.view = view
        self.ctx = ctx
        p = self.params = config.params
        self.s = sign(view.role)
        self.width = p.get("width", "strategist")
        self.sees_limit = bool(p.get("negotiator_sees_limit", False))
        self.accept_words = p.get("accept_words", True)
        self.strategist = ctx.llm(p.get("strategist_model") or config.model, "strategist")
        self.negotiator = ctx.llm(config.model, "negotiator")
        facts = brief(view, ctx.protocol)
        self.strategist_system = PROMPTS.render(STRATEGIST_PROMPT, **facts)
        self.negotiator_system = PROMPTS.render(NEGOTIATOR_PROMPTS[self.sees_limit], **facts)

    # The strategist

    def _plan_problems(self, plan: BandPlan) -> list[str]:
        f = lambda p: money(self.view, p)  # noqa: E731
        bad = [f"{name} {f(price)}" for name, price in (("target", plan.target), ("worst", plan.worst))
               if past_limit(self.view, price)]
        return [f"{' and '.join(bad)} are past your walk-away price. Set the band within it."] if bad else []

    async def plan(self, obs: Observation) -> BandPlan:
        prompt = (f"The conversation so far:\n\n{transcript_text(obs, self.ctx.protocol)}\n\n"
                  "Set the band for your side's next message.")

        async def ask(text: str) -> BandPlan:
            resp = await self.strategist.complete(LLMRequest.of(
                text, system=self.strategist_system, output_schema=BandPlan,
                max_tokens=self.params.get("max_tokens"), tags={"stage": "strategist"}))
            assert isinstance(resp.parsed, BandPlan)
            return resp.parsed

        plan = await ask(prompt)
        if found := self._plan_problems(plan):     # one retry; make_band keeps whatever comes back in the limit
            plan = await ask(f"{prompt}\n\n{OWN_NOTE} Your previous band was rejected: {' '.join(found)}")
        return plan

    # The negotiator

    def _brief(self, band: Band, plan: BandPlan) -> str:
        f = lambda p: money(self.view, p)  # noqa: E731
        lines = [f"{OWN_NOTE} Your strategist's brief for this turn:", f"- Their latest message: {plan.read}"]
        if self.width == "full" and not self.sees_limit:
            lines.append(f"- Suggested price: about {f(band.target)}. You choose; your own system rejects prices "
                         "you may not offer.")
        elif band.best is None:
            lines.append(f"- Offer {f(band.worst)} or better for you; aim for about {f(band.target)}.")
        elif abs(band.best - band.worst) <= TOL:
            lines.append(f"- Offer exactly {f(band.target)}.")
        else:
            lines.append(f"- Offer between {f(band.worst)} and {f(band.best)}; aim for about {f(band.target)}.")
        if not (self.width == "full" and not self.sees_limit):
            lines.append(f"- Accept their latest offer only if it is {f(band.worst)} or better for you.")
        lines.append(f"- Angle: {plan.angle}")
        return "\n".join(lines)

    def check(self, d: Decision, obs: Observation, band: Band) -> list[str]:
        """What keeps a decision from being sent: outside the band, a price written past the walk-away price,
        or agreement words without accepting. Worded so a negotiator that doesn't know the limit learns nothing
        about it beyond the band it was given."""
        f = lambda p: money(self.view, p)  # noqa: E731
        out: list[str] = []
        say_band = not (self.width == "full" and not self.sees_limit)
        if d.action == "offer":
            if d.price is None:
                out.append("an offer needs a price.")
            elif not band.allows(self.s, d.price):
                out.append(f"{f(d.price)} is outside the band for this turn"
                           + (f" ({f(band.worst)} to {f(band.best)})." if say_band and band.best is not None else
                              f" ({f(band.worst)} or better for you)." if say_band else "."))
        elif d.action == "accept":
            closing = closing_price(obs)
            prices = [p for p in (d.price, closing) if p is not None]
            if not prices:
                out.append("there is no offer from the other side to accept.")
            elif any(self.s * p < self.s * band.worst - TOL for p in prices):
                out.append(f"you may only accept an offer of {f(band.worst)} or better for you." if say_band else
                           "you may not accept that offer.")
        found = find_prices(d.message)
        if any(p.currency for p in found):
            found = [p for p in found if p.currency]
        if bad := sorted({p.value for p in found if past_limit(self.view, p.value)}):
            out.append(f"the message mentions {', '.join(map(f, bad))}. Don't write those amounts, not even to "
                       "reject them.")
        if self.accept_words and d.action != "accept" and reads_as_agreement(d.message):
            out.append(AGREEMENT_FEEDBACK)
        return out

    def repair(self, d: Decision, obs: Observation, band: Band) -> Decision | None:
        """A safe version of a decision that failed its checks twice: an offer clamped into the band with a
        plain message. None when there is nothing to repair (fall back instead)."""
        if d.action not in ("offer", "accept"):
            return None
        price = band.clamp(self.s, d.price) if d.action == "offer" and d.price is not None else band.target
        return Decision(action="offer", price=price, message=f"I can do {money(self.view, price)}.")

    async def negotiate(self, obs: Observation, band: Band, plan: BandPlan, feedback: str | None) -> Decision:
        messages: list[ChatMessage] = with_note(transcript(obs, self.ctx.protocol), self._brief(band, plan))
        if feedback:
            messages = with_note(messages, feedback)
        resp = await self.negotiator.complete(LLMRequest(
            messages=messages, system=self.negotiator_system, output_schema=Decision,
            max_tokens=self.params.get("max_tokens"), tags={"stage": "negotiator"}))
        assert isinstance(resp.parsed, Decision)
        return resp.parsed

    async def respond(self, obs: Observation) -> Move:
        try:
            plan = await self.plan(obs)
        except LLMError as e:
            return safe_move(obs, f"strategist: {type(e).__name__}: {e}")
        band = make_band(self.view, plan, self.width)
        meta = {"band": {"worst": band.worst, "target": band.target, "best": band.best}, "plan": plan.model_dump()}
        vetoes: list[str] = []
        feedback = None
        for _ in range(2):
            try:
                d = await self.negotiate(obs, band, plan, feedback)
            except LLMError as e:
                return safe_move(obs, f"negotiator: {type(e).__name__}: {e}", **meta)
            if not (found := self.check(d, obs, band)):
                return self._final(to_move(d, **({"vetoes": vetoes} if vetoes else {}), **meta), obs)
            vetoes += found
            feedback = f"{OWN_NOTE} Your previous draft was rejected: {' '.join(found)} Decide again."
        if (fixed := self.repair(d, obs, band)) is None:
            return safe_move(obs, "failed its checks", vetoes=vetoes, rejected=d.model_dump(), **meta)
        return self._final(to_move(fixed, vetoes=vetoes, repaired=True, rejected=d.model_dump(), **meta), obs)

    def _final(self, move: Move, obs: Observation) -> Move:
        """Last line of defence: whatever the band, never send a move past the walk-away price."""
        if limit_problems(self.view, move.action or ActionKind.MESSAGE, move.price, move.text, closing_price(obs)):
            return safe_move(obs, "past the limit despite the band", rejected=move.meta.get("decision"),
                             band=move.meta["band"], plan=move.meta["plan"])
        return move
