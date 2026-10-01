"""Offline stand-ins for testing an agent without a model or a match."""
from __future__ import annotations

import random
from collections import deque
from collections.abc import Callable, Iterable

from pydantic import BaseModel, ValidationError

from agent_sdk.context import AgentContext, ProtocolInfo
from agent_sdk.llm import LLMBadOutput, LLMRequest, LLMResponse, Usage
from agent_sdk.roles import Role

Reply = str | BaseModel | Exception
Responder = Callable[[LLMRequest], Reply]

FREETEXT = ProtocolInfo(name="freetext", structured=False,
                        description="Messages are plain text. A deal closes when one side clearly accepts the other's "
                                    "most recent price in writing.")
STRUCTURED = ProtocolInfo(name="structured", structured=True,
                          description="Each message carries an action (offer, accept, reject, message, walk_away) and, "
                                      "for offers, a price. A deal closes when one side accepts the other's standing "
                                      "offer.")


class FakeLLM:
    """Answers from a queue of scripted replies, or from a function of the request. A reply that is
    an exception is raised, so tests can inject timeouts and bad output. Every request is kept in
    `requests`."""

    def __init__(self, replies: Iterable[Reply] | Responder = ()):
        self.requests: list[LLMRequest] = []
        self._responder = replies if callable(replies) else None
        self._queue: deque[Reply] = deque() if callable(replies) else deque(replies)

    async def complete(self, req: LLMRequest) -> LLMResponse:
        self.requests.append(req)
        reply = self._responder(req) if self._responder else self._queue.popleft()
        if isinstance(reply, Exception):
            raise reply
        text = reply.model_dump_json() if isinstance(reply, BaseModel) else reply
        parsed = None
        if req.output_schema:
            try:
                parsed = req.output_schema.model_validate_json(text)
            except ValidationError as e:
                raise LLMBadOutput(str(e), text=text) from e
        prompt = (req.system or "") + "".join(m.content for m in req.messages)
        return LLMResponse(text=text, parsed=parsed, usage=Usage(input_tokens=len(prompt) // 4,
                                                                 output_tokens=len(text) // 4),
                           provider="fake", profile="fake", model="fake", stop_reason="end_turn")


def context(role: Role, llm: FakeLLM | None = None, protocol: ProtocolInfo = FREETEXT,
            seed: int = 0) -> AgentContext:
    """A context whose every model profile answers from `llm`."""
    return AgentContext(role=role, rng=random.Random(seed), protocol=protocol,
                        llm_factory=(lambda profile, stage: llm) if llm else None)
