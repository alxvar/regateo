"""The negotiator proposes inside a price band (docs/02 O4). A strategist call reads the conversation and sets
the band for the turn; the negotiator picks the price and writes the message; code only holds the move to the
band and the hard limits. Unlike docs/02's drawing, code never computes the band itself (docs/06 §3.3): the
band's `width` param sweeps how much of the strategist's choice the negotiator may override.

v2 over v1: the strategist is shown a ledger of facts computed by code (both sides' offers so far, how far each
has moved, messages left) and a prompt that ties each concession to the other side's movement, because v1 gave
away its whole range in unreciprocated steps against opponents that barely moved. The negotiator is also told
not to quote their prices, which the mentions veto turned into bare "I can do $X." messages.

v3 over v2: with `standing`, code vetoes an offer worse for us than the other side's standing offer, which every
architecture's smoke and round-01 matches showed (a buyer bidding $135 against a $91 ask). The feedback asks the
negotiator to accept their offer or to offer better for us than it; which stays with the model (approved by the
user behind a switch, 2026-10-02).

v4 over v3: a fix, always on: v2 and v3's ledger said "They have moved $X from their first offer (not toward
you)" exactly when they had moved toward us (the sign was inverted), under a prompt that ties our concessions to
their movement. With `clock`, the strategist's ledger also states when the negotiation ends (messages sent by each
side; when the limit is known, whether our next message is the last of all; when it isn't, that it is unknown)
and how close the two sides are (the gap between the latest offers, and whether theirs is already better for us),
with a prompt on closing a small gap before the messages run out. In round-01, 62 of the 84 no-deals with a hidden
limit ended with their offer within our limit when we sent our last message. With `plain_final`, the negotiator
is told not to call an offer final unless it is its last message: in round-01 it did in about half the matches
and moved from it in about half of those. Code states facts only; the prices stay with the models.

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
from agent_sdk.guards import limit_problems, past_limit, reads_as_agreement, standing_problems
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
    own_messages_sent,
    safe_move,
    their_offers,
    to_move,
    transcript,
    transcript_text,
    with_note,
)
from .offers import our_offers, their_floor

PROMPTS = PromptDir(Path(__file__).parent / "prompts")
STRATEGIST_PROMPTS = {True: "strategist_system.v2", False: "strategist_system.v1"}
CLOCK_STRATEGIST_PROMPT = "strategist_system.v3"
NEGOTIATOR_PROMPTS = {(True, False): "negotiator_system_limit.v2", (False, False): "negotiator_system.v2",
                      (True, True): "negotiator_system_limit.v3", (False, True): "negotiator_system.v3"}
WIDTHS = ("strategist", "full")


def strategist_prompt(params: dict) -> str:
    return CLOCK_STRATEGIST_PROMPT if params.get("clock") else STRATEGIST_PROMPTS[bool(params.get("hold", True))]


def negotiator_prompt(params: dict) -> str:
    return NEGOTIATOR_PROMPTS[bool(params.get("negotiator_sees_limit", False)), bool(params.get("plain_final"))]


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


def ledger(view: PrivateView, obs: Observation, clock: bool = False) -> str:
    """Facts for the strategist, computed from the conversation: both sides' offers in order, how far each side
    has moved since its first offer, and how many messages are left. With `clock`, also when the negotiation can
    end and how close the latest offers are (`clock_facts`). No advice."""
    f = lambda p: money(view, p)  # noqa: E731
    s = sign(view.role)
    ours, theirs = our_offers(obs), their_offers(obs)
    lines = ["Facts from your own system (computed, not from the other side):"]
    lines.append("- Your offers so far: " + (", ".join(map(f, ours)) if ours else "none"))
    lines.append("- Their offers so far (the last amount of their own in each message): "
                 + (", ".join(map(f, theirs)) if theirs else "none"))
    if len(ours) >= 2:
        lines.append(f"- You have moved {f(abs(ours[-1] - ours[0]))} from your first offer.")
    if len(theirs) >= 2:
        moved = s * (theirs[-1] - theirs[0])           # positive: they have moved toward us (v2/v3 had it inverted)
        lines.append(f"- They have moved {f(abs(moved))} from their first offer"
                     + ("" if moved > 0 else " (not toward you)" if moved < 0 else "") + ".")
    if view.max_rounds is not None:
        left = max(view.max_rounds - own_messages_sent(obs), 0)
        lines.append(f"- Messages left for your side, including the next one: {left} of {view.max_rounds}.")
    if clock:
        lines += clock_facts(view, obs, ours)
    return "\n".join(lines)


def last_message(view: PrivateView, obs: Observation) -> bool:
    """Whether our next message is the last of the negotiation: the limit is known and the other side has no
    message left after it."""
    if view.max_rounds is None:
        return False
    theirs_sent = len(obs.history) - own_messages_sent(obs)
    return view.max_rounds - theirs_sent <= 0


def clock_facts(view: PrivateView, obs: Observation, ours: list[float]) -> list[str]:
    """When the negotiation can end and how close the two sides are, as facts: messages sent by each side, what
    is left after our next message (or that the limit is unknown), and the gap between our last offer and their
    standing offer, read defensively (`their_floor`) so a planted amount can't make it look smaller."""
    f = lambda p: money(view, p)  # noqa: E731
    s = sign(view.role)
    mine = own_messages_sent(obs)
    lines = [f"- Messages sent so far: {mine} by your side, {len(obs.history) - mine} by theirs."]
    if view.max_rounds is None:
        lines.append("- The limit on messages is unknown: the negotiation can end, with no deal, after any message, "
                     "including your next one.")
    elif last_message(view, obs):
        lines.append("- Your next message is the last of the negotiation: they can't answer it, so an offer in it "
                     "can't be accepted.")
    else:
        theirs_left = view.max_rounds - (len(obs.history) - mine)
        lines.append(f"- After your next message, they can send {theirs_left} more.")
    floor = their_floor(obs)
    if floor is not None and ours:
        gap = s * (ours[-1] - floor)                   # positive: our last offer is better for us than theirs
        lines.append(f"- Gap between your last offer ({f(ours[-1])}) and their latest offer ({f(floor)}): "
                     f"{f(abs(gap))}." if gap >= 0 else
                     f"- Their latest offer ({f(floor)}) is already better for you than your last offer "
                     f"({f(ours[-1])}), by {f(-gap)}.")
    return lines


class RangedAgent:
    """Params:
    - `width`: "strategist" (default: the strategist's own band), "full" (any price within the walk-away
      price), or a number w >= 0 (w times the market range around the strategist's target; 0 makes the
      negotiator a writer).
    - `hold`: use the v2 strategist prompt and show it the ledger of offers (default true; false is v1's).
    - `negotiator_sees_limit`: show the negotiator our walk-away price (default false).
    - `strategist_model`: model profile for the strategist (default: the config's model).
    - `accept_words` (veto agreement words when not accepting, default true).
    - `standing`: veto an offer worse for us than their standing offer (default false).
    - `clock`: show the strategist when the negotiation ends and how close the offers are, with the v3
      strategist prompt; the negotiator's brief says when its message is the last (default false; needs `hold`).
    - `plain_final`: tell the negotiator not to call an offer final unless it is its last message (default false).
    - `max_tokens`."""

    def __init__(self, config: AgentConfig, view: PrivateView, ctx: AgentContext):
        self.name = config.name
        self.view = view
        self.ctx = ctx
        p = self.params = config.params
        self.s = sign(view.role)
        self.width = p.get("width", "strategist")
        self.hold = bool(p.get("hold", True))
        self.sees_limit = bool(p.get("negotiator_sees_limit", False))
        self.accept_words = p.get("accept_words", True)
        self.standing = bool(p.get("standing", False))
        self.clock = bool(p.get("clock", False))
        self.plain_final = bool(p.get("plain_final", False))
        self.strategist = ctx.llm(p.get("strategist_model") or config.model, "strategist")
        self.negotiator = ctx.llm(config.model, "negotiator")
        facts = brief(view, ctx.protocol)
        self.strategist_system = PROMPTS.render(strategist_prompt(p), **facts)
        self.negotiator_system = PROMPTS.render(negotiator_prompt(p), **facts)

    # The strategist

    def _plan_problems(self, plan: BandPlan) -> list[str]:
        f = lambda p: money(self.view, p)  # noqa: E731
        bad = [f"{name} {f(price)}" for name, price in (("target", plan.target), ("worst", plan.worst))
               if past_limit(self.view, price)]
        return [f"{' and '.join(bad)} are past your walk-away price. Set the band within it."] if bad else []

    async def plan(self, obs: Observation) -> BandPlan:
        facts = f"{ledger(self.view, obs, self.clock)}\n\n" if self.hold else ""
        prompt = (f"The conversation so far:\n\n{transcript_text(obs, self.ctx.protocol)}\n\n{facts}"
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

    def _brief(self, band: Band, plan: BandPlan, obs: Observation) -> str:
        f = lambda p: money(self.view, p)  # noqa: E731
        lines = [f"{OWN_NOTE} Your strategist's brief for this turn:", f"- Their latest message: {plan.read}"]
        if self.clock and last_message(self.view, obs):
            lines.append("- This is your last message: they can't answer it, so an offer in it can't be accepted.")
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
        agreement words without accepting, or with `standing` an offer worse for us than theirs. Worded so a
        negotiator that doesn't know the limit learns nothing about it beyond the band it was given."""
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
            if self.standing:
                out += standing_problems(self.view, "offer", d.price, their_floor(obs))
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
        messages: list[ChatMessage] = with_note(transcript(obs, self.ctx.protocol), self._brief(band, plan, obs))
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
