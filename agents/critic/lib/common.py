"""Helpers shared by the critic versions: the brief every prompt fills, the conversation as chat turns, the
offers so far, the hard-limit checks and the safe fallback."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Literal

from agent_sdk import ActionKind, ChatMessage, LLMError, Move, Observation, PrivateView, ProtocolInfo, Role, sign
from agent_sdk.guards import limit_problems, reads_as_agreement
from agent_sdk.prices import fmt_price, stated_prices
from pydantic import BaseModel, Field

OPENING = "(The negotiation begins. You make the first move.)"
OWN_NOTE = "[Note from your own system, not from the other side]"
AGREEMENT_FEEDBACK = ("the message could be read as accepting, but you are not accepting. Don't use words like "
                      "'deal', 'agree', 'accept', 'sounds good' or 'works for me' unless you accept.")
TOL = 0.005
MAX_MESSAGE = 1500                     # characters


class Decision(BaseModel):
    # `price` is required (null allowed) and `message` capped: with an optional price, guided decoding let Qwen
    # skip it and write the message first, and it then ran on to max_tokens in about half the samples.
    action: Literal["offer", "accept", "reject", "message", "walk_away"]
    price: float | None = Field(description="price offered or accepted; null otherwise")
    message: str = Field(max_length=MAX_MESSAGE, description="what the other side reads")


def money(view: PrivateView, price: float) -> str:
    return fmt_price(price, view.currency)


def brief(view: PrivateView, protocol: ProtocolInfo) -> dict[str, str]:
    """The placeholders every system prompt fills: role, item, walk-away price, public facts and rules."""
    rules = [f"- Each side gets at most {view.max_rounds} messages. After that, there is no deal."
             if view.max_rounds is not None else
             "- There is a limit on the number of messages, but you don't know it."]
    if view.time_limit_s:
        rules.append(f"- The whole negotiation must finish within {view.time_limit_s:.0f} seconds.")
    if view.opponent_range:
        lo, hi = sorted(view.opponent_range)
        rules.append(f"- Market intelligence: the other side's walk-away price is likely between {money(view, lo)} "
                     f"and {money(view, hi)}.")
    if view.context:
        rules.append(f"- {view.context}")
    return {
        "role": view.role.value,
        "item": view.item,
        "reservation": money(view, view.reservation),
        "walkaway_rule": "Never sell below it." if view.role is Role.SELLER else "Never pay more than it.",
        "market_low": money(view, view.market_low),
        "market_high": money(view, view.market_high),
        "rules": "\n".join(rules),
        "protocol": protocol.description,
    }


def near(a: float, b: float) -> bool:
    return abs(a - b) <= TOL


def our_offers(obs: Observation) -> list[float]:
    me = obs.view.role
    return [m.move.price for m in obs.history
            if m.sender is me and m.move.action is ActionKind.OFFER and m.move.price is not None]


def _readings(obs: Observation) -> list[tuple[list[float], list[float]]]:
    """For each opponent message that names a price: (amounts of its own, amounts it quotes from us), in order
    of appearance. On a structured platform the delivered offer price is the only amount of its own."""
    me = obs.view.role
    ours: list[float] = []
    out: list[tuple[list[float], list[float]]] = []
    for m in obs.history:
        if m.sender is me:
            ours += stated_prices(m.text) + ([m.move.price] if m.move.price is not None else [])
        elif m.move.action is ActionKind.OFFER and m.move.price is not None:
            out.append(([m.move.price], []))
        elif named := stated_prices(m.text):
            quoted = [p for p in named if any(near(p, q) for q in ours)]
            out.append(([p for p in named if p not in quoted], quoted))
    return out


def their_offers(obs: Observation) -> list[float]:
    """Their offers so far as facts for the model, oldest first: the last amount of its own in each message that
    names one ("another seller is at $120, but I can do $135" offers $135). Amounts we wrote first are quotes."""
    return [own[-1] for own, _ in _readings(obs) if own]


def standing_offer(obs: Observation) -> float | None:
    theirs = their_offers(obs)
    return theirs[-1] if theirs else None


def closing_price(obs: Observation) -> float | None:
    """The price an acceptance from us could close at, read defensively for the limit check: the amount worst
    for us in their latest message that names one, so a planted or quoted number can't talk us past the limit.
    A message that only restates our own amounts ("fine, $91") closes at those."""
    s = sign(obs.view.role)
    for own, quoted in reversed(_readings(obs)):
        if amounts := own or quoted:
            return min(amounts, key=lambda p: s * p)
    return None


def opening_price(view: PrivateView) -> float:
    """The end of the market range that favours us, never past our walk-away price."""
    s = sign(view.role)
    return s * max(s * view.market_low, s * view.market_high, s * view.reservation)


def own_messages_sent(obs: Observation) -> int:
    return sum(m.sender is obs.view.role for m in obs.history)


def transcript(obs: Observation, protocol: ProtocolInfo) -> list[ChatMessage]:
    """The conversation as chat turns: theirs as user turns, ours as the decisions we made."""
    me = obs.view.role
    out: list[ChatMessage] = []
    if not obs.history or obs.history[0].sender is me:
        out.append(ChatMessage(role="user", content=OPENING))
    for m in obs.history:
        if m.sender is me:
            d = m.move.meta.get("decision")
            content = Decision.model_validate(d).model_dump_json() if d else (m.text or "(no message)")
            out.append(ChatMessage(role="assistant", content=content))
            continue
        text = m.text or "(no message)"
        if protocol.structured and m.move.action:
            price = f" {money(obs.view, m.move.price)}" if m.move.price is not None else ""
            text = f"[{m.move.action.value}{price}]\n{text}"
        out.append(ChatMessage(role="user", content=f"[message {m.idx + 1}] {text}"))
    return out


def with_note(messages: list[ChatMessage], note: str) -> list[ChatMessage]:
    """`messages` with `note` added to the last user turn (or as a new one)."""
    if messages and messages[-1].role == "user":
        return [*messages[:-1], ChatMessage(role="user", content=f"{messages[-1].content}\n\n{note}")]
    return [*messages, ChatMessage(role="user", content=note)]


def problems(d: Decision, obs: Observation, *, accept_words: bool) -> list[str]:
    """What breaks a hard invariant in a decision (docs/06 §3.4), as feedback the model can act on."""
    out = limit_problems(obs.view, d.action, d.price, d.message, closing_price(obs))
    if accept_words and d.action != "accept" and reads_as_agreement(d.message):
        out.append(AGREEMENT_FEEDBACK)
    return out


def to_move(d: Decision, **meta: object) -> Move:
    return Move(text=d.message, action=ActionKind(d.action), price=d.price, meta={"decision": d.model_dump(), **meta})


def safe_move(obs: Observation, reason: str, **meta: object) -> Move:
    """Code's move when the model fails: restate our last offer, or open at the market end that favours us."""
    ours = our_offers(obs)
    price = ours[-1] if ours else opening_price(obs.view)
    return Move(text=f"My offer stands at {money(obs.view, price)}.", action=ActionKind.OFFER, price=price,
                meta={"fallback": reason, **meta})


async def guarded(decide: Callable[[str | None], Awaitable[Decision]], obs: Observation, *,
                  accept_words: bool, retries: int = 1) -> Move:
    """Decide, veto a decision that breaks an invariant and decide again with the reasons and the draft, then
    repair. `decide(feedback)` makes one model call; feedback is None on the first."""
    vetoes: list[str] = []
    feedback = None
    for _ in range(retries + 1):
        try:
            d = await decide(feedback)
        except LLMError as e:
            return safe_move(obs, f"{type(e).__name__}: {e}", **({"vetoes": vetoes} if vetoes else {}))
        found = problems(d, obs, accept_words=accept_words)
        if not found:
            return to_move(d, **({"vetoes": vetoes} if vetoes else {}))
        vetoes += found
        feedback = (f"{OWN_NOTE} Your previous draft was rejected: {' '.join(found)}\nThe rejected draft: "
                    f"{d.model_dump_json()}\nDecide again.")
    return repair(d, obs, vetoes)


def repair(d: Decision, obs: Observation, vetoes: list[str]) -> Move:
    """A decision that failed its checks again: keep its action and price when they are within the limit, with a
    plain message in place of the one that failed; otherwise code's safe move."""
    meta = {"vetoes": vetoes, "repaired": True, "rejected": d.model_dump()}
    v = obs.view
    if d.action == "offer" and d.price is not None and not limit_problems(v, "offer", d.price, "", None,
                                                                            mentions=False):
        return to_move(Decision(action="offer", price=d.price, message=f"I can do {money(v, d.price)}."), **meta)
    closing = closing_price(obs)
    if d.action == "accept" and closing is not None and not limit_problems(v, "accept", closing, "", closing,
                                                                            mentions=False):
        return to_move(Decision(action="accept", price=closing, message=f"I accept {money(v, closing)}."), **meta)
    return safe_move(obs, "failed its checks", vetoes=vetoes, rejected=d.model_dump())



def transcript_text(obs: Observation, protocol: ProtocolInfo) -> str:
    """The conversation as one text, for a model that reviews it rather than takes part. Every line of a
    message is quoted with "> ", so text inside a message can't pass for a header."""
    me = obs.view.role
    if not obs.history:
        return "(No messages yet. Your side makes the first move.)"
    blocks = []
    for m in obs.history:
        who = "your side" if m.sender is me else "the other side"
        intent = ""
        if m.move.action is not None and (m.sender is me or protocol.structured):
            price = f" {money(obs.view, m.move.price)}" if m.move.price is not None else ""
            intent = f" ({m.move.action.value}{price})"
        quoted = "\n".join(f"> {line}" for line in (m.text or "(no message)").splitlines() or [""])
        blocks.append(f"[message {m.idx + 1}, {who}{intent}]\n{quoted}")
    return "\n\n".join(blocks)
