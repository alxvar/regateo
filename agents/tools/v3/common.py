"""Helpers for tools v3: v2's (our own offers read from the history even when the move's action is missing, a
model error retried once, optional sanitizing) plus a new reading of acceptances. lib.common vetoed an
acceptance whenever their latest message named any amount past our limit, so "another buyer offered $95, my
final offer is $150" could not be accepted by a seller whose limit is $108 (17 vetoed acceptances of an offer
within our limit against LLM opponents in round-01, 8 of those matches ended with no deal). The referee prices
our acceptance at the amount our message names, so v3 checks that amount and asks the message to name it.
Optionally an offer worse for us than their standing offer is flagged (agent_sdk.guards.standing_problems)."""
from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from agent_sdk import ActionKind, LLMError, Move, Observation, sign
from agent_sdk.guards import limit_problems, reads_as_agreement, standing_problems
from agent_sdk.prices import stated_prices

from ..lib.common import (  # noqa: F401  (re-exported for the v3 modules)
    AGREEMENT_FEEDBACK,
    OWN_NOTE,
    Decision,
    _readings,
    brief,
    closing_price,
    money,
    near,
    opening_price,
    standing_offer,
    their_offers,
    to_move,
    transcript,
    with_note,
)


def offer_to_accept(obs: Observation) -> float | None:
    """The price an acceptance takes when it names none: their offer in their latest message that names an
    amount (the last amount of their own, as `their_offers` reads it), or, when it only restates our amounts
    ("fine, $91"), the one of those worst for us."""
    s = sign(obs.view.role)
    for own, quoted in reversed(_readings(obs)):
        if own:
            return own[-1]
        if quoted:
            return min(quoted, key=lambda p: s * p)
    return None


def defensive_offer(obs: Observation) -> float | None:
    """Their standing offer read defensively, for `standing_problems`: the amount of their own worst for us in
    their latest message that names one, so a planted or quoted amount can't make that check fire."""
    s = sign(obs.view.role)
    for own, _ in reversed(_readings(obs)):
        if own:
            return min(own, key=lambda p: s * p)
    return None


def accept_problems(d: Decision, obs: Observation) -> list[str]:
    """What breaks the walk-away price in an acceptance: the price it closes at is the one the message names
    (that is how a free-text reader prices it), so that price must be within the limit and be in the message.
    Every amount in the message is checked too (mentions), as for any move."""
    v = obs.view
    price = d.price if d.price is not None else offer_to_accept(obs)
    out = limit_problems(v, "accept", price, d.message, None)
    if not out and price is not None and not any(near(p, price) for p in stated_prices(d.message)):
        out.append(f"say the price you accept in the message, for example \"I accept {money(v, price)}.\", so it "
                   "can't be read as accepting a different amount.")
    return out


def problems(d: Decision, obs: Observation, *, accept_words: bool, standing: bool = False) -> list[str]:
    """What breaks a hard invariant in a decision (docs/06 §3.4), as feedback the model can act on; with
    `standing`, also an offer worse for us than their standing offer (opt-in, approved 2026-10-02)."""
    if d.action == "accept":
        out = accept_problems(d, obs)
    else:
        out = limit_problems(obs.view, d.action, d.price, d.message, None)
    if accept_words and d.action != "accept" and reads_as_agreement(d.message):
        out.append(AGREEMENT_FEEDBACK)
    if standing:
        out += standing_problems(obs.view, d.action, d.price, defensive_offer(obs))
    return out


def our_offers(obs: Observation, sent: list[float] | None = None) -> list[float]:
    """Our offers so far, oldest first. From the history: the move's price when it is an offer (or has no
    action), else the price of the decision we logged. If the history has none, `sent`, what the agent
    recorded itself."""
    me = obs.view.role
    out: list[float] = []
    for m in obs.history:
        if m.sender is not me:
            continue
        d = m.move.meta.get("decision") or {}
        if m.move.price is not None and m.move.action in (None, ActionKind.OFFER):
            out.append(m.move.price)
        elif d.get("action") == "offer" and d.get("price") is not None:
            out.append(float(d["price"]))
    return out or list(sent or [])


def safe_move(obs: Observation, reason: str, sent: list[float] | None = None, **meta: object) -> Move:
    """Code's move when the model fails: restate our last offer, or open at the market end that favours us."""
    ours = our_offers(obs, sent)
    price = ours[-1] if ours else opening_price(obs.view)
    return Move(text=f"My offer stands at {money(obs.view, price)}.", action=ActionKind.OFFER, price=price,
                meta={"fallback": reason, **meta})


_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")


def strip_failing(d: Decision, obs: Observation, *, accept_words: bool) -> Decision | None:
    """`d` without the sentences that break the message checks (a price past our limit, agreement words), when
    what is left passes every check and still says the price for an offer. None when that isn't possible."""
    v = obs.view
    keep = []
    for s in _SENTENCE.split(d.message.strip()):
        if limit_problems(v, "message", None, s, None) or (accept_words and d.action != "accept"
                                                           and reads_as_agreement(s)):
            continue
        keep.append(s)
    text = " ".join(keep).strip()
    if not text or text == d.message.strip():
        return None
    if d.action in ("offer", "accept") and d.price is not None and not any(
            near(p, d.price) for p in stated_prices(text)):
        return None
    out = Decision(action=d.action, price=d.price, message=text)
    return out if not problems(out, obs, accept_words=accept_words) else None


async def guarded(decide: Callable[[str | None], Awaitable[Decision]], obs: Observation, *, accept_words: bool,
                  sent: list[float] | None = None, sanitize: bool = False, standing: bool = False,
                  retries: int = 1) -> Move:
    """Decide, veto a decision that breaks an invariant and decide again with the reasons and the draft, then
    repair. `decide(feedback)` makes one model call; feedback is None on the first. With `standing`, an offer
    worse for us than their standing offer is vetoed once too, but a second draft that fails only that check
    is sent as the model wrote it: what to offer stays with the model."""
    vetoes: list[str] = []
    feedback = None
    errors = 0
    attempts = 0
    d: Decision | None = None
    while attempts <= retries:
        try:
            d = await decide(feedback)
        except LLMError as e:
            errors += 1
            if errors > 1:
                return safe_move(obs, f"{type(e).__name__}: {e}", sent, **({"vetoes": vetoes} if vetoes else {}))
            continue                                   # a model error is retried once and costs no veto retry
        attempts += 1
        found = problems(d, obs, accept_words=accept_words, standing=standing)
        if not found:
            return to_move(d, **({"vetoes": vetoes} if vetoes else {}))
        vetoes += found
        feedback = (f"{OWN_NOTE} Your previous draft was rejected: {' '.join(found)}\nThe rejected draft: "
                    f"{d.model_dump_json()}\nDecide again.")
    assert d is not None
    if standing and not problems(d, obs, accept_words=accept_words):
        return to_move(d, vetoes=vetoes, standing_kept=True)
    return repair(d, obs, vetoes, sent, sanitize=sanitize, accept_words=accept_words)


def repair(d: Decision, obs: Observation, vetoes: list[str], sent: list[float] | None = None, *,
           sanitize: bool = False, accept_words: bool = True) -> Move:
    """A decision that failed its checks again: with `sanitize`, its own message minus the offending
    sentences; else keep its action and price when they are within the limit, with a plain message in place
    of the one that failed; otherwise code's safe move."""
    meta = {"vetoes": vetoes, "repaired": True, "rejected": d.model_dump()}
    v = obs.view
    if sanitize and (cleaned := strip_failing(d, obs, accept_words=accept_words)) is not None:
        return to_move(cleaned, **meta, sanitized=True)
    if d.action == "offer" and d.price is not None and not limit_problems(v, "offer", d.price, "", None,
                                                                            mentions=False):
        return to_move(Decision(action="offer", price=d.price, message=f"I can do {money(v, d.price)}."), **meta)
    closing = d.price if d.price is not None else offer_to_accept(obs)
    if d.action == "accept" and closing is not None and not limit_problems(v, "accept", closing, "", None,
                                                                            mentions=False):
        return to_move(Decision(action="accept", price=closing, message=f"I accept {money(v, closing)}."), **meta)
    return safe_move(obs, "failed its checks", sent, vetoes=vetoes, rejected=d.model_dump())


def horizon_note(obs: Observation, horizon: tuple[int, int]) -> str:
    """Facts about where we are in a match whose message limit is unknown: which of our messages this is, the
    range of limits the platform's negotiations use (a setting, from the public bench rules), and whether the
    negotiation could end after this message."""
    lo, hi = horizon
    n = sum(m.sender is obs.view.role for m in obs.history) + 1     # this message's number
    out = (f"{OWN_NOTE} This is your message {n}. The message limit is unknown; negotiations here allow "
           f"{lo} to {hi} messages per side.")
    if n >= hi:
        out += " The negotiation will most likely end after this message."
    elif n >= lo:
        out += " The negotiation could end after this message."
    elif n == lo - 1:
        out += " The negotiation could end after your next message."
    return f"{out} A negotiation that ends with no deal scores zero."


def endgame_note(obs: Observation, horizon: tuple[int, int] | None = None) -> str:
    """Facts about where we are in the match, for the model. When the message limit is unknown: with a
    `horizon` range, `horizon_note`; without, nothing."""
    v = obs.view
    if v.max_rounds is None:
        return horizon_note(obs, horizon) if horizon else ""
    sent = sum(m.sender is v.role for m in obs.history)
    left = v.max_rounds - sent                              # messages of ours left, including this one
    first = not obs.history or obs.history[0].sender is v.role
    if left <= 0:
        return ""
    if left == 1:
        tail = ("They will get one more message after it, and can accept it or not." if first else
                "The negotiation ends after it: they cannot reply, so only an acceptance from you can close a deal.")
        return (f"{OWN_NOTE} This is your final message, message {sent + 1} of {v.max_rounds}. {tail} "
                "A negotiation that ends with no deal scores zero.")
    return (f"{OWN_NOTE} This is your message {sent + 1} of {v.max_rounds}; {left - 1} more of yours after this "
            "one. A negotiation that ends with no deal scores zero.")
