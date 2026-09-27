"""Gym spec: a head-to-head experiment between agent A and agent B."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator

from regateo.agents.base import AgentSpec
from regateo.core.ids import derive_seed
from regateo.core.roles import Role
from regateo.runner.runner import MatchJob
from regateo.runner.specs import ExperimentSpec, cell_of, resolve_agent


class GymSpec(ExperimentSpec):
    """`duel`: A plays B, every scenario twice with roles swapped.
    `benchmark`: A and B each play the same opponents on the same scenarios, roles and seeds."""

    mode: Literal["duel", "benchmark"] = "duel"
    a: AgentSpec
    b: AgentSpec
    opponents: list[AgentSpec] = Field(default_factory=list)
    roles: list[Role] = Field(default_factory=lambda: [Role.SELLER, Role.BUYER])   # benchmark only

    @field_validator("a", "b", mode="before")
    @classmethod
    def _agent(cls, v: Any) -> AgentSpec:
        return resolve_agent(v)

    @field_validator("opponents", mode="before")
    @classmethod
    def _opponents(cls, v: Any) -> list[AgentSpec]:
        return [resolve_agent(x) for x in v]

    def jobs(self) -> list[MatchJob]:
        if self.a.ref().key == self.b.ref().key:
            raise ValueError("A and B are the same agent configuration")
        if self.mode == "benchmark" and not self.opponents:
            raise ValueError("benchmark mode needs opponents")
        common = {"protocol": self.protocol, "detector": self.detector, "sim_clock": self.sim_clock}
        jobs = []
        for i, s in enumerate(self.sample()):
            cell = cell_of(s)
            if self.mode == "duel":
                seed = derive_seed(self.seed, i)
                for a_role in (Role.SELLER, Role.BUYER):
                    seller, buyer = (self.a, self.b) if a_role is Role.SELLER else (self.b, self.a)
                    jobs.append(MatchJob(key=f"{i}-a{a_role.value[0]}", scenario=s, seller=seller, buyer=buyer,
                                         seed=seed, meta={"mode": "duel", "pair": str(i), "a_role": a_role.value,
                                                          "cell": cell}, **common))
                continue
            for k, opp in enumerate(self.opponents):
                for role in self.roles:
                    seed = derive_seed(self.seed, i, k, role.value)
                    pair = f"{i}-{k}-{role.value[0]}"
                    for subject, agent in (("a", self.a), ("b", self.b)):
                        seller, buyer = (agent, opp) if role is Role.SELLER else (opp, agent)
                        jobs.append(MatchJob(key=f"{pair}-{subject}", scenario=s, seller=seller, buyer=buyer,
                                             seed=seed, meta={"mode": "benchmark", "pair": pair, "subject": subject,
                                                              "role": role.value, "opponent": opp.label,
                                                              "cell": cell}, **common))
        return jobs
