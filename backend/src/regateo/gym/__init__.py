"""Head-to-head experiments: agent A vs B over paired scenarios with roles swapped."""
from regateo.gym.report import GymReport, build_gym_report
from regateo.gym.run import run_gym
from regateo.gym.spec import GymSpec

__all__ = ["GymReport", "GymSpec", "build_gym_report", "run_gym"]
