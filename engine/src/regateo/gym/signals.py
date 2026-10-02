"""Exploit signals: patterns in an agent's play that an opponent could use against it.

Counted from the stored messages and the referee's readings, so they describe what the other side saw, whichever
agent played. They came from reading climb round-01's transcripts: agents that froze on one canned line, conceded
when the other side hadn't moved, countered above a price already on the table, called offers final and moved
again, or named their own limit. They are signals for a person to read, not scores: a concession without a move
from the other side can be right, and a reading can be wrong (`regateo readings`).
"""
from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable

from pydantic import BaseModel

from regateo.core.messages import Message, ReadKind
from regateo.core.outcome import EndReason, Outcome
from regateo.core.roles import Role, other, sign
from regateo.core.scenario import Scenario
from regateo.referee.prices import stated_prices
from regateo.storage.store import MatchRow

# Calling an offer final, or saying it is at a limit.
FINAL = re.compile(
    r"\b(?:final (?:offer|price|number|answer|position)|best and final|last offer|rock[- ]bottom"
    r"|absolute (?:max(?:imum)?|min(?:imum)?|lowest|highest|limit|ceiling|floor)"
    r"|my (?:limit|ceiling|floor|maximum|minimum)"
    r"|(?:can't|cannot|can not|won't) go (?:any )?(?:lower|higher|further|above|below))", re.IGNORECASE)
MOVE_TOLERANCE = 0.005    # in market widths: smaller price changes are not moves
NEAR_LIMIT = 0.01         # in market widths: a price this close to an agent's walk-away price names it


class Signals(BaseModel):
    """One agent's counts across its matches in a run, against one opponent or all of them."""
    agent: str
    opponent: str = "all"
    matches: int = 0
    turns: int = 0              # its messages
    repeats: int = 0            # messages repeating one of its earlier messages in the match, word for word
    rewritten: int = 0          # messages its own checks rewrote or replaced (move meta `repaired` or `fallback`)
    concessions: int = 0        # offers worse for it than its previous offer
    unreciprocated: int = 0     # of those, made when the other side's offer hadn't improved since its previous one
    dominated: int = 0          # matches where it offered worse for itself than the other side's standing offer
    no_deals: int = 0
    missed: int = 0             # no-deal matches where the other side had offered a price within its limit
    finals: int = 0             # offers it called final or at its limit (FINAL)
    broken_finals: int = 0      # of those, followed by a further concession
    near_limit: int = 0         # matches where its text named a price within NEAR_LIMIT of its own walk-away
                                # price, other than one the other side had named

    def add(self, s: Signals) -> None:
        for name in Signals.model_fields:
            if name not in ("agent", "opponent"):
                setattr(self, name, getattr(self, name) + getattr(s, name))


def match_signals(messages: list[Message], scenario: Scenario, role: Role, outcome: Outcome,
                  agent: str = "", opponent: str = "") -> Signals:
    """The signals of the side playing `role` in one finished match."""
    s = Signals(agent=agent, opponent=opponent, matches=1)
    u = sign(role)
    width = scenario.market_high - scenario.market_low
    tol = MOVE_TOLERANCE * width
    limit = scenario.seller_reservation if role is Role.SELLER else scenario.buyer_reservation
    mine: float | None = None            # our last offer, in u-space
    theirs: float | None = None          # their standing offer, in u-space
    theirs_then: float | None = None     # their standing offer when we made our last offer
    finals: list[float] = []             # offers we called final and haven't conceded from yet
    said: set[str] = set()
    named: list[float] = []              # every amount the other side has named
    dominated = acceptable = near = False
    for m in messages:
        r = m.reading
        offer = r.price if r is not None and r.kind is ReadKind.OFFER else None
        if m.sender is other(role):
            named += stated_prices(m.text, negated=True)
            if offer is not None:
                theirs = u * offer
                acceptable |= theirs >= u * limit
            continue
        s.turns += 1
        text = " ".join(m.text.lower().split())
        s.repeats += text in said
        said.add(text)
        s.rewritten += bool(m.move.meta.get("repaired") or m.move.meta.get("fallback"))
        near |= any(abs(p - limit) <= NEAR_LIMIT * width and not any(abs(p - q) <= tol for q in named)
                    for p in stated_prices(m.text, negated=True))
        if offer is None:
            continue
        mine_now = u * offer
        dominated |= theirs is not None and mine_now < theirs - tol
        if mine is not None and mine_now < mine - tol:
            s.concessions += 1
            moved = theirs is not None and (theirs_then is None or theirs > theirs_then + tol)
            s.unreciprocated += not moved
        broken = [f for f in finals if mine_now < f - tol]
        s.broken_finals += len(broken)
        finals = [f for f in finals if f not in broken]
        if FINAL.search(m.text):
            s.finals += 1
            finals.append(mine_now)
        mine, theirs_then = mine_now, theirs
    s.dominated, s.near_limit = int(dominated), int(near)
    if not outcome.deal and outcome.end_reason is not EndReason.ERROR:
        s.no_deals = 1
        s.missed = int(acceptable)
    return s


class SidePlay(BaseModel):
    """One agent's side of one finished match."""
    agent: str
    opponent: str
    role: Role
    scenario: Scenario
    outcome: Outcome
    messages: list[Message]


def sides(row: MatchRow, messages: list[Message]) -> list[SidePlay]:
    """The sides of a finished match worth counting: in a benchmark the subject's, otherwise both."""
    if row.status != "done" or row.outcome is None:
        return []
    names = {Role.SELLER: row.seller.name, Role.BUYER: row.buyer.name}
    roles = [Role(row.meta["role"])] if "subject" in row.meta else [Role.SELLER, Role.BUYER]
    return [SidePlay(agent=names[r], opponent=row.meta.get("opponent") or names[other(r)], role=r,
                     scenario=row.scenario, outcome=row.outcome, messages=messages) for r in roles]


def run_signals(plays: Iterable[SidePlay], by_opponent: bool = False) -> list[Signals]:
    """Signals per agent, in the order agents first appear; with `by_opponent`, each agent's total is followed by
    one row per opponent."""
    totals: dict[str, Signals] = {}
    per: dict[str, dict[str, Signals]] = defaultdict(dict)
    for p in plays:
        s = match_signals(p.messages, p.scenario, p.role, p.outcome, p.agent, p.opponent)
        totals.setdefault(p.agent, Signals(agent=p.agent)).add(s)
        per[p.agent].setdefault(p.opponent, Signals(agent=p.agent, opponent=p.opponent)).add(s)
    out = []
    for agent, total in totals.items():
        out.append(total)
        if by_opponent:
            out += [per[agent][k] for k in sorted(per[agent])]
    return out
