"""Deterministic provider for tests and offline runs: no network, no cost."""
from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable, Iterable

from pydantic import BaseModel, ValidationError

from regateo.llm.errors import LLMBadOutput
from regateo.llm.profiles import ModelProfile
from regateo.llm.types import LLMRequest, LLMResponse, Usage

Reply = str | BaseModel | Exception
Responder = Callable[[LLMRequest], Reply]


class FakeProvider:
    """Answers from a queue of scripted replies, or from a function of the request.

    An Exception reply is raised, so tests can inject timeouts and bad output.
    Every request is kept in `requests` for assertions.
    """

    provider = "fake"

    def __init__(self, replies: Iterable[Reply] | Responder = (), *, profile_name: str = "fake",
                 delay_s: float = 0.0):
        self.profile_name = profile_name
        self.delay_s = delay_s
        self.requests: list[LLMRequest] = []
        if callable(replies):
            self._responder: Responder | None = replies
            self._queue: deque[Reply] = deque()
        else:
            self._responder = None
            self._queue = deque(replies)

    @classmethod
    def from_profile(cls, profile: ModelProfile) -> FakeProvider:
        return cls(lambda req: "ok", profile_name=profile.name)

    async def complete(self, req: LLMRequest) -> LLMResponse:
        self.requests.append(req)
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
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
        usage = Usage(input_tokens=len(prompt) // 4, output_tokens=len(text) // 4)
        return LLMResponse(text=text, parsed=parsed, usage=usage, provider=self.provider,
                           profile=self.profile_name, model="fake", stop_reason="end_turn")
