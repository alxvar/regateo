"""Claude through the official Anthropic SDK."""
from __future__ import annotations

import os
import time
from typing import Any

import anthropic
from pydantic import ValidationError

from regateo.llm.errors import LLMBadOutput, LLMError, LLMRateLimited, LLMRefusal, LLMTimeout
from regateo.llm.profiles import ModelProfile
from regateo.llm.types import LLMRequest, LLMResponse, Usage


class AnthropicProvider:
    provider = "anthropic"

    def __init__(self, profile: ModelProfile):
        self.profile = profile
        self.profile_name = profile.name
        api_key = os.environ.get(profile.api_key_env) if profile.api_key_env else None
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key,
            base_url=profile.base_url,
            timeout=profile.timeout_s,
            max_retries=profile.max_retries,
        )

    def _kwargs(self, req: LLMRequest) -> tuple[Any, dict[str, Any]]:
        p = self.profile
        kwargs: dict[str, Any] = {
            "model": p.model,
            "max_tokens": req.max_tokens or p.max_tokens,
            "messages": [{"role": m.role, "content": m.content} for m in req.messages],
        }
        if req.system:
            # Cache the system prompt: it's identical across turns and matches.
            kwargs["system"] = [{"type": "text", "text": req.system, "cache_control": {"type": "ephemeral"}}]
        if p.thinking:
            kwargs["thinking"] = p.thinking
        if effort := req.effort or p.effort:
            kwargs["output_config"] = {"effort": effort}
        extra = dict(p.extra)
        betas = extra.pop("betas", None)
        kwargs.update(extra)          # e.g. fallbacks
        if betas:
            kwargs["betas"] = betas
            return self._client.beta.messages, kwargs
        return self._client.messages, kwargs

    async def complete(self, req: LLMRequest) -> LLMResponse:
        api, kwargs = self._kwargs(req)
        start = time.perf_counter()
        try:
            if req.output_schema:
                msg = await api.parse(output_format=req.output_schema, **kwargs)
            else:
                msg = await api.create(**kwargs)
        except ValidationError as e:
            raise LLMBadOutput(f"response does not match {req.output_schema.__name__}: {e}") from e
        except anthropic.RateLimitError as e:
            retry_after = e.response.headers.get("retry-after")
            raise LLMRateLimited(str(e), retry_after_s=float(retry_after) if retry_after else None) from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"{e.status_code}: {e.message}", status=e.status_code,
                           retryable=e.status_code >= 500) from e
        except anthropic.APITimeoutError as e:
            raise LLMTimeout(str(e)) from e
        except anthropic.APIConnectionError as e:
            raise LLMError(f"connection error: {e}", retryable=True) from e
        latency = time.perf_counter() - start

        if msg.stop_reason == "refusal":
            category = getattr(msg.stop_details, "category", None) if msg.stop_details else None
            raise LLMRefusal(f"{msg.model} refused (category={category})", category=category)

        text = "".join(b.text for b in msg.content if b.type == "text")
        parsed = getattr(msg, "parsed_output", None) if req.output_schema else None
        if req.output_schema and parsed is None:
            raise LLMBadOutput(f"no parsed output (stop_reason={msg.stop_reason})", text=text)

        u = msg.usage
        usage = Usage(
            input_tokens=u.input_tokens,
            output_tokens=u.output_tokens,
            cache_read_tokens=u.cache_read_input_tokens or 0,
            cache_write_tokens=u.cache_creation_input_tokens or 0,
        )
        return LLMResponse(
            text=text, parsed=parsed, usage=usage, cost_usd=self.profile.price.cost(usage),
            latency_s=latency, provider=self.provider, profile=self.profile_name,
            model=msg.model, stop_reason=msg.stop_reason,
        )
