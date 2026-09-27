"""Arena spec: a round robin across a roster of agents."""
from __future__ import annotations

from itertools import combinations
from typing import Any

from pydantic import field_validator

from regateo.agents.base import AgentSpec
from regateo.core.ids import derive_seed
from regateo.runner.runner import MatchJob
from regateo.runner.specs import ExperimentSpec, cell_of, resolve_agent


class ArenaSpec(ExperimentSpec):
    roster: list[AgentSpec]
    games_per_pair: int = 20               # scenarios per pairing; each is played in both role assignments

    @field_validator("roster", mode="before")
    @classmethod
    def _roster(cls, v: Any) -> list[AgentSpec]:
        roster = [resolve_agent(x) for x in v]
        labels = [a.label for a in roster]
        if len(set(labels)) != len(labels):
            raise ValueError(f"roster labels must be unique (set `name`): {labels}")
        if len(roster) < 2:
            raise ValueError("an arena needs at least two agents")
        return roster

    def jobs(self) -> list[MatchJob]:
        scenarios = self.sample()
        common = {"protocol": self.protocol, "detector": self.detector, "sim_clock": self.sim_clock}
        jobs = []
        for i, j in combinations(range(len(self.roster)), 2):
            for g in range(self.games_per_pair):
                s = scenarios[g % len(scenarios)]
                seed = derive_seed(self.seed, i, j, g)
                for seller_idx, buyer_idx in ((i, j), (j, i)):
                    jobs.append(MatchJob(
                        key=f"{i}v{j}-{g}-s{seller_idx}", scenario=s, seller=self.roster[seller_idx],
                        buyer=self.roster[buyer_idx], seed=seed,
                        meta={"pair": f"{i}v{j}", "game": g, "seller": self.roster[seller_idx].label,
                              "buyer": self.roster[buyer_idx].label, "cell": cell_of(s)}, **common))
        return jobs
