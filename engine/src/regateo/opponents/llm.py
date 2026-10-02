"""LLM sparring partners: one model plays the whole game (docs/02 O1), with a persona prompt
(tough, naive, manipulator, injector, exploiter) or without one (`o1`, the plain end-to-end agent).

This is the engine's own copy of what our first agent did, kept apart from `agents/` so that agent
builders never see what their opponents run. Its requests are byte-for-byte those of the original, so
stored matches against these opponents still replay from the LLM cache.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from agent_sdk import ActionKind, AgentContext, ChatMessage, LLMError, LLMRequest, Move, Observation, PrivateView, Role
from agent_sdk.prompts import PromptDir
from pydantic import BaseModel, Field

from regateo.agents.base import AgentSpec, register
from regateo.opponents.common import fmt_price, safe_fallback

PROMPTS = PromptDir(Path(__file__).parent / "prompts")
PERSONAS = sorted(p.name.removeprefix("persona_").split(".")[0] for p in PROMPTS.folder.glob("persona_*.md"))


class Decision(BaseModel):
    action: Literal["offer", "accept", "reject", "message", "walk_away"]
    price: float | None = Field(default=None, description="price offered or accepted; null otherwise")
    message: str = Field(description="what the other side reads")


OPENING_STUB = "(The negotiation begins. You make the first move.)"
DEFAULT_PROMPT = "negotiator_system.v1"


class EndToEndAgent:
    """Params: `prompt` (default negotiator_system.v1), `persona` (set from the kind), `effort`, `max_tokens`."""

    stage = "o1"

    @staticmethod
    def prompt_refs(spec: AgentSpec) -> list[str]:
        """Prompt files this spec renders, for its identity (AgentSpec.ref)."""
        refs = [spec.params.get("prompt", DEFAULT_PROMPT)]
        persona = spec.params.get("persona") or (spec.kind.split(":", 1)[1] if spec.kind.startswith("persona:")
                                                 else None)
        if persona:
            refs.append(f"persona_{persona}")
        return refs

    def __init__(self, spec: AgentSpec, view: PrivateView, ctx: AgentContext):
        self.name = spec.label
        self.view = view
        self.ctx = ctx
        self.params = spec.params
        self.llm = ctx.llm(spec.model, self.stage)
        self.system = self._system_prompt()

    def _system_prompt(self) -> str:
        v = self.view
        f = lambda p: fmt_price(p, v.currency)  # noqa: E731
        extra = []
        if v.max_rounds is not None:
            extra.append(f"- Each side gets at most {v.max_rounds} messages. After that, there is no deal.")
        else:
            extra.append("- There is a limit on the number of messages, but you don't know it.")
        if v.time_limit_s:
            extra.append(f"- The whole negotiation must finish within {v.time_limit_s:.0f} seconds.")
        if v.opponent_range:
            lo, hi = sorted(v.opponent_range)
            extra.append("- Market intelligence: the other side's walk-away price is likely between "
                         f"{f(lo)} and {f(hi)}.")
        if v.context:
            extra.append(f"- {v.context}")
        return PROMPTS.render(
            self.params.get("prompt", DEFAULT_PROMPT),
            role=v.role.value,
            item=v.item,
            reservation=f(v.reservation),
            walkaway_rule="Never sell below it." if v.role is Role.SELLER else "Never pay more than it.",
            market_low=f(v.market_low),
            market_high=f(v.market_high),
            extra_info="\n".join(extra),
            protocol=self.ctx.protocol.description,
            persona=self.persona_text(),
        )

    def persona_text(self) -> str:
        """What fills the system prompt's $persona: the persona's prompt, or nothing."""
        persona = self.params.get("persona")
        return f"\n{PROMPTS.render(f'persona_{persona}')}\n" if persona else ""

    def _messages(self, obs: Observation) -> list[ChatMessage]:
        me = obs.view.role
        out: list[ChatMessage] = []
        if not obs.history or obs.history[0].sender is me:
            out.append(ChatMessage(role="user", content=OPENING_STUB))
        for m in obs.history:
            if m.sender is me:
                decision = m.move.meta.get("decision")
                content = (Decision.model_validate(decision).model_dump_json() if decision
                           else m.text or "(no message)")
                out.append(ChatMessage(role="assistant", content=content))
                continue
            text = m.text or "(no message)"
            if m.move.action and self.ctx.protocol.structured:
                price = f" {fmt_price(m.move.price, obs.view.currency)}" if m.move.price is not None else ""
                text = f"[{m.move.action.value}{price}]\n{text}"
            out.append(ChatMessage(role="user", content=f"[message {m.idx + 1}] {text}"))
        return out

    async def respond(self, obs: Observation) -> Move:
        try:
            resp = await self.llm.complete(LLMRequest(
                messages=self._messages(obs),
                system=self.system,
                output_schema=Decision,
                effort=self.params.get("effort"),
                max_tokens=self.params.get("max_tokens"),
                tags={"stage": self.stage},
            ))
        except LLMError as e:
            return safe_fallback(obs, f"{type(e).__name__}: {e}")
        d = resp.parsed
        assert isinstance(d, Decision)
        return Move(text=d.message, action=ActionKind(d.action), price=d.price, meta={"decision": d.model_dump()})


class PersonaAgent(EndToEndAgent):
    stage = "persona"


@register("o1", prompts=EndToEndAgent.prompt_refs, prompt_dir=PROMPTS)
def build_o1(spec: AgentSpec, view: PrivateView, ctx: AgentContext) -> EndToEndAgent:
    return EndToEndAgent(spec, view, ctx)


@register("persona:", prompts=PersonaAgent.prompt_refs, prompt_dir=PROMPTS)
def build_persona(spec: AgentSpec, view: PrivateView, ctx: AgentContext) -> PersonaAgent:
    persona = spec.kind.split(":", 1)[1]
    if persona not in PERSONAS:
        raise ValueError(f"unknown persona {persona!r}; known: {PERSONAS}")
    spec = spec.model_copy(update={"params": {**spec.params, "persona": persona}})
    return PersonaAgent(spec, view, ctx)
