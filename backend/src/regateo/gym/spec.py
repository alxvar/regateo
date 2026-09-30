"""Gym spec: a head-to-head experiment between agent A and agent B."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from regateo.agents.base import AgentSpec
from regateo.core.config import configs_dir, load_yaml_dict
from regateo.core.ids import derive_seed
from regateo.core.roles import Role
from regateo.gym.early import EarlyStop
from regateo.runner.runner import MatchJob
from regateo.runner.specs import ExperimentSpec, cell_of, resolve_agent

# What a bench fixes. A gym that names a bench may not set these itself: results on one bench
# stay comparable across experiments, and changing any of them means a new bench version.
BENCH_FIELDS = ("mode", "opponents", "roles", "scenarios", "protocol", "detector", "reader", "seed", "sim_clock",
                "tiers", "purpose")


def load_bench(name: str) -> dict[str, Any]:
    path = configs_dir() / "benches" / f"{name}.yaml"
    if not path.exists():
        raise ValueError(f"no bench {name!r} (configs/benches/{name}.yaml)")
    return load_yaml_dict(path)


class GymSpec(ExperimentSpec):
    """`duel`: A plays B, every scenario twice with roles swapped.
    `benchmark`: A and B each play the same opponents on the same scenarios, roles and seeds.

    In YAML, a benchmark can also be written as `reference: <agent>` (B) plus `challengers: [...]`
    (A first, the rest in `extra`); each challenger is compared with the reference on paired matches.
    `bench: <name>` takes opponents, scenarios and rules from configs/benches/<name>.yaml, and
    `tier: <name>` plays only the first N scenarios per cell, as that bench's `tiers` sets. A tier's
    matches are a subset of the full bench's, so they replay from the cache when the full bench runs."""

    mode: Literal["duel", "benchmark"] = "duel"
    a: AgentSpec
    b: AgentSpec
    extra: list[AgentSpec] = Field(default_factory=list)   # benchmark only: more challengers, like A
    opponents: list[AgentSpec] = Field(default_factory=list)
    roles: list[Role] = Field(default_factory=lambda: [Role.SELLER, Role.BUYER])   # benchmark only
    bench: str | None = None
    tier: str | None = None
    tiers: dict[str, int] = Field(default_factory=dict)     # tier name -> scenarios per cell
    purpose: Literal["dev", "holdout"] = "dev"               # set by the bench; decides the promotion checks
    early_stop: EarlyStop | None = None                       # benchmark only: stop clear losers (gym.early)

    @model_validator(mode="before")
    @classmethod
    def _sugar(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        data = dict(data)
        if bench := data.get("bench"):
            fixed = load_bench(bench)
            clash = sorted(k for k in fixed if k in data and k in BENCH_FIELDS)
            if clash:
                raise ValueError(f"bench {bench!r} fixes {clash}; make a new bench to change them")
            data = {**fixed, **data}
        if "reference" in data:
            if "b" in data:
                raise ValueError("give either `reference` or `b`")
            data["b"] = data.pop("reference")
        if "challengers" in data:
            if "a" in data or "extra" in data:
                raise ValueError("give either `challengers` or `a`/`extra`")
            first, *rest = data.pop("challengers") or [None]
            if first is None:
                raise ValueError("`challengers` needs at least one agent")
            data["mode"] = data.get("mode", "benchmark")
            data["a"], data["extra"] = first, rest
        return data

    @field_validator("early_stop", mode="before")
    @classmethod
    def _early_stop(cls, v: Any) -> Any:
        return {} if v is True else None if v is False else v

    @field_validator("a", "b", mode="before")
    @classmethod
    def _agent(cls, v: Any) -> AgentSpec:
        return resolve_agent(v)

    @field_validator("extra", "opponents", mode="before")
    @classmethod
    def _agents(cls, v: Any) -> list[AgentSpec]:
        return [resolve_agent(x) for x in v]

    def subjects(self) -> dict[str, AgentSpec]:
        """Agents under test, by subject key: a, b, then a2, a3... for the extra challengers."""
        return {"a": self.a, "b": self.b, **{f"a{n}": s for n, s in enumerate(self.extra, start=2)}}

    def per_cell_cap(self) -> int | None:
        if self.tier is None:
            return None
        if self.tier not in self.tiers:
            raise ValueError(f"unknown tier {self.tier!r}; this gym has {sorted(self.tiers) or 'none'}")
        return self.tiers[self.tier]

    def jobs(self) -> list[MatchJob]:
        subjects = self.subjects()
        keys = [s.ref().key for s in subjects.values()]
        if len(set(keys)) != len(keys):
            raise ValueError("two subjects have the same agent configuration")
        if self.mode == "benchmark" and not self.opponents:
            raise ValueError("benchmark mode needs opponents")
        if self.mode == "duel" and self.extra:
            raise ValueError("extra challengers need benchmark mode")
        cap = self.per_cell_cap()
        common = {"protocol": self.protocol, "detector": self.detector, "reader": self.reader,
                  "sim_clock": self.sim_clock}
        jobs = []
        scenarios = self.sample()
        # Interleave the cells (1st scenario of each cell, then the 2nd...), so any prefix of the run, which
        # early stopping judges, covers every cell. i indexes the full set, so seeds don't shift by order or tier.
        order = sorted(range(len(scenarios)), key=lambda i: int(scenarios[i].id.rsplit(":", 1)[1]))
        for i in order:
            s = scenarios[i]
            if cap is not None and int(s.id.rsplit(":", 1)[1]) >= cap:
                continue
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
                    for subject, agent in subjects.items():
                        seller, buyer = (agent, opp) if role is Role.SELLER else (opp, agent)
                        jobs.append(MatchJob(key=f"{pair}-{subject}", scenario=s, seller=seller, buyer=buyer,
                                             seed=seed, meta={"mode": "benchmark", "pair": pair, "subject": subject,
                                                              "role": role.value, "opponent": opp.label,
                                                              "cell": cell}, **common))
        return jobs
