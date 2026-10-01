"""Settings shared by gym and arena specs, and loading them from YAML."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from regateo.agents.base import AgentSpec
from regateo.core.config import configs_dir, load_yaml
from regateo.core.scenario import Scenario, ScenarioSpec, sample_scenarios
from regateo.runner.runner import RunSettings


def resolve_scenario_spec(value: str | dict[str, Any] | ScenarioSpec) -> ScenarioSpec:
    """A spec, a dict, or the name of configs/scenarios/<name>.yaml (or a path to a YAML file)."""
    if isinstance(value, ScenarioSpec):
        return value
    if isinstance(value, dict):
        return ScenarioSpec.model_validate(value)
    path = Path(value)
    if path.suffix not in (".yaml", ".yml"):
        path = configs_dir() / "scenarios" / f"{value}.yaml"
    return load_yaml(path, ScenarioSpec)


class ExperimentSpec(BaseModel):
    name: str
    scenarios: ScenarioSpec = Field(default_factory=ScenarioSpec)
    protocol: str = "structured"
    detector: str = "structured"
    reader: str = "rules"                   # rules | llm:<profile> | shadow:rules+llm:<profile>
    seed: int = 0
    sim_clock: bool = False                 # simulated latency; use for code-only agents
    settings: RunSettings = Field(default_factory=RunSettings)

    @field_validator("scenarios", mode="before")
    @classmethod
    def _scenarios(cls, v: Any) -> ScenarioSpec:
        return resolve_scenario_spec(v)

    def sample(self) -> list[Scenario]:
        return sample_scenarios(self.scenarios, self.seed)


def resolve_agent(v: Any) -> AgentSpec:
    return AgentSpec.resolve(v)


def cell_of(scenario: Scenario) -> str:
    """Grid cell of a sampled scenario (ids look like `<seed>:<cell>:<i>`)."""
    parts = scenario.id.split(":")
    return parts[1] if len(parts) == 3 else "all"
