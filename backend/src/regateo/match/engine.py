"""Run one negotiation between two agents under a protocol, with a referee watching."""
from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable

from pydantic import BaseModel

from regateo.core.agent import Abort, Agent, Observation
from regateo.core.messages import ActionKind, Message, Move, Transcript
from regateo.core.outcome import EndReason, Outcome
from regateo.core.roles import Role, other
from regateo.core.scenario import Scenario
from regateo.match.clock import Clock, RealClock
from regateo.protocol.base import TurnProtocol
from regateo.referee.detect import DealDetector, DealEvent
from regateo.referee.scoring import score
from regateo.storage.store import Store

OnMessage = Callable[[Message], Awaitable[None]]


class MatchResult(BaseModel):
    outcome: Outcome
    transcript: Transcript


async def run_match(
    scenario: Scenario,
    seller: Agent,
    buyer: Agent,
    *,
    protocol: TurnProtocol,
    detector: DealDetector,
    rng: random.Random,
    clock: Clock | None = None,
    store: Store | None = None,
    match_id: str | None = None,
    on_message: OnMessage | None = None,
) -> MatchResult:
    """Alternate turns until a deal, a walk-away, an error, or the round or time budget runs out.

    Messages go to `store` (if given) as they happen, so live views can follow the match.
    """
    clock = clock or RealClock()
    rules = scenario.rules
    agents = {Role.SELLER: seller, Role.BUYER: buyer}
    views = {r: scenario.view_for(r) for r in Role}
    transcript = Transcript()
    role = protocol.first_mover(scenario, rng)

    def end(reason: EndReason, event: DealEvent | None = None, **extra: object) -> MatchResult:
        outcome = score(scenario, event, reason, messages=len(transcript))
        if extra:
            outcome = outcome.model_copy(update=extra)
        return MatchResult(outcome=outcome, transcript=transcript)

    for idx in range(rules.max_messages):
        history = protocol.view_of(transcript.messages, role)
        last = transcript.last()
        start = clock.now()
        obs = Observation(
            view=views[role],
            history=history,
            incoming=history[-1].text if last and last.sender is not role else None,
            message_idx=idx,
            elapsed_s=start,
            remaining_s=rules.time_limit_s - start if rules.time_limit_s else None,
        )
        try:
            async with asyncio.timeout(rules.per_message_timeout_s):
                move = await agents[role].respond(obs)
        except TimeoutError:
            move = Move(text="", meta={"timeout": True})
        except Abort:
            raise
        except Exception as e:   # noqa: BLE001 - any agent failure ends the match, blamed on that side
            return end(EndReason.ERROR, error_by=role, detail=f"{role} agent failed: {type(e).__name__}: {e}")
        clock.after_response()
        now = clock.now()
        if rules.time_limit_s is not None and now > rules.time_limit_s:
            return end(EndReason.TIME_LIMIT)     # arrived too late: not delivered

        move = protocol.normalise(move, rules)
        message = Message(idx=idx, sender=role, text=move.text, move=move, t=now, latency_s=now - start)
        transcript.append(message)
        if store and match_id:
            await store.append_message(match_id, message)
        if on_message:
            await on_message(message)

        if move.action is ActionKind.WALK_AWAY:
            return end(EndReason.WALK_AWAY)
        if event := await detector.check(transcript.messages):
            return end(EndReason.DEAL, event)
        role = other(role)

    return end(EndReason.ROUND_LIMIT)
