"""LLM sparring partners: the O1 engine with a persona prompt (tough, naive, manipulator, injector).

These double as the opponent simulators docs/03 §2.5 mentions: build once, reuse for
evaluation, offline data, and maybe live lookahead.
"""
from __future__ import annotations

from pathlib import Path

from regateo.agents.base import AgentContext, AgentSpec, register
from regateo.agents.baselines.o1 import EndToEndAgent
from regateo.core.scenario import PrivateView

PERSONAS = sorted(p.name.removeprefix("persona_").split(".")[0]
                  for p in (Path(__file__).parents[1] / "prompts").glob("persona_*.md"))


class PersonaAgent(EndToEndAgent):
    stage = "persona"


@register("persona:")
def build_persona(spec: AgentSpec, view: PrivateView, ctx: AgentContext) -> PersonaAgent:
    persona = spec.kind.split(":", 1)[1]
    if persona not in PERSONAS:
        raise ValueError(f"unknown persona {persona!r}; known: {PERSONAS}")
    spec = spec.model_copy(update={"params": {**spec.params, "persona": persona}})
    return PersonaAgent(spec, view, ctx)
