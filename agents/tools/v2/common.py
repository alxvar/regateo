"""Helpers for tools v2: lib.common with three fixes. Our own offers are read from the history even when the
move's action is missing, and from the agent's own record when the history has none (v1 restated our
opening price in 8 of 17 fallbacks, late in the match). A model error is retried once before falling back.
Optionally a message that fails its checks is repaired by dropping the offending sentences."""
from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from agent_sdk import ActionKind, LLMError, Move, Observation
from agent_sdk.guards import limit_problems, reads_as_agreement
from agent_sdk.prices import stated_prices

from ..lib.common import (  # noqa: F401  (re-exported for the v2 modules)
    AGREEMENT_FEEDBACK,
    OWN_NOTE,
    Decision,
    brief,
    closing_price,
    money,
    near,
    opening_price,
    problems,
    standing_offer,
    their_offers,
    to_move,
    transcript,
    with_note,
)


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
                  sent: list[float] | None = None, sanitize: bool = False, retries: int = 1) -> Move:
    """Decide, veto a decision that breaks an invariant and decide again with the reasons and the draft, then
    repair. `decide(feedback)` makes one model call; feedback is None on the first."""
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
        found = problems(d, obs, accept_words=accept_words)
        if not found:
            return to_move(d, **({"vetoes": vetoes} if vetoes else {}))
        vetoes += found
        feedback = (f"{OWN_NOTE} Your previous draft was rejected: {' '.join(found)}\nThe rejected draft: "
                    f"{d.model_dump_json()}\nDecide again.")
    assert d is not None
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
    closing = closing_price(obs)
    if d.action == "accept" and closing is not None and not limit_problems(v, "accept", closing, "", closing,
                                                                            mentions=False):
        return to_move(Decision(action="accept", price=closing, message=f"I accept {money(v, closing)}."), **meta)
    return safe_move(obs, "failed its checks", sent, vetoes=vetoes, rejected=d.model_dump())


def endgame_note(obs: Observation) -> str:
    """Facts about where we are in the match, for the model (none when the message limit is unknown)."""
    v = obs.view
    if v.max_rounds is None:
        return ""
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
