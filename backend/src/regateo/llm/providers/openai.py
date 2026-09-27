"""OpenAI-API models through the official openai SDK. Used with vLLM for local models."""
from __future__ import annotations

import os
import re
import time
from typing import Any

import openai
from pydantic import ValidationError

from regateo.llm.errors import LLMBadOutput, LLMError, LLMRateLimited, LLMRefusal, LLMTimeout
from regateo.llm.profiles import ModelProfile
from regateo.llm.types import LLMRequest, LLMResponse, Usage

_THINK = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


def strip_thinking(text: str) -> str:
    """Drop inline reasoning. vLLM with a reasoning parser returns it separately; without one,
    Qwen-style models put it in <think> tags at the start of the content."""
    text = _THINK.sub("", text)
    if "</think>" in text:                     # opening tag was in the chat template
        text = text.split("</think>", 1)[1]
    return text.strip()


class OpenAIProvider:
    provider = "openai"

    def __init__(self, profile: ModelProfile):
        self.profile = profile
        self.profile_name = profile.name
        api_key = os.environ.get(profile.api_key_env) if profile.api_key_env else None
        self._client = openai.AsyncOpenAI(
            api_key=api_key or "EMPTY",       # vLLM accepts any key unless started with --api-key
            base_url=profile.base_url,
            timeout=profile.timeout_s,
            max_retries=profile.max_retries,
        )

    def _kwargs(self, req: LLMRequest) -> dict[str, Any]:
        p = self.profile
        messages: list[dict[str, str]] = []
        if req.system:
            messages.append({"role": "system", "content": req.system})
        messages += [{"role": m.role, "content": m.content} for m in req.messages]
        kwargs: dict[str, Any] = {
            "model": p.model,
            "messages": messages,
            "max_tokens": req.max_tokens or p.max_tokens,
        }
        if req.output_schema:
            # vLLM enforces this with guided decoding; hosted APIs with structured outputs.
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": req.output_schema.__name__,
                                "schema": req.output_schema.model_json_schema()},
            }
        kwargs.update(p.extra)                # e.g. temperature, extra_body for vLLM options
        return kwargs

    async def complete(self, req: LLMRequest) -> LLMResponse:
        start = time.perf_counter()
        try:
            resp = await self._client.chat.completions.create(**self._kwargs(req))
        except openai.RateLimitError as e:
            raise LLMRateLimited(str(e)) from e
        except openai.APIStatusError as e:
            raise LLMError(f"{e.status_code}: {e.message}", status=e.status_code,
                           retryable=e.status_code >= 500) from e
        except openai.APITimeoutError as e:
            raise LLMTimeout(str(e)) from e
        except openai.APIConnectionError as e:
            raise LLMError(f"connection error ({self.profile.base_url}): {e}", retryable=True) from e
        latency = time.perf_counter() - start

        choice = resp.choices[0]
        if choice.finish_reason == "content_filter":
            raise LLMRefusal(f"{resp.model} content filter")
        text = strip_thinking(choice.message.content or "")

        parsed = None
        if req.output_schema:
            if choice.finish_reason == "length":
                raise LLMBadOutput("output truncated at max_tokens", text=text)
            try:
                parsed = req.output_schema.model_validate_json(text)
            except ValidationError as e:
                raise LLMBadOutput(f"response does not match {req.output_schema.__name__}: {e}",
                                   text=text) from e

        usage = Usage()
        if resp.usage:
            cached = getattr(resp.usage.prompt_tokens_details, "cached_tokens", None) or 0
            usage = Usage(input_tokens=resp.usage.prompt_tokens - cached,
                          output_tokens=resp.usage.completion_tokens, cache_read_tokens=cached)
        return LLMResponse(
            text=text, parsed=parsed, usage=usage, cost_usd=self.profile.price.cost(usage),
            latency_s=latency, provider=self.provider, profile=self.profile_name,
            model=resp.model, stop_reason=choice.finish_reason,
        )
