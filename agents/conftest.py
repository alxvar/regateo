"""Agent tests import their package as regateo_agents.<architecture>.<version> (agent_sdk.packages)."""
from pathlib import Path

from agent_sdk import packages

packages.mount(Path(__file__).parent)
