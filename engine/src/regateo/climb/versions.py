"""Agent versions as the climb loop sees them: the prompts a config uses, and new versions made by
copying a parent (agents/<architecture>/<version>/, agent_sdk.packages)."""
from __future__ import annotations

import re
import shutil

from agent_sdk import packages
from agent_sdk.prompts import PromptDir

from regateo.agents import AgentSpec
from regateo.core.config import agents_dir


def prompt_dir(spec: AgentSpec) -> PromptDir:
    if not packages.is_version(spec.kind):
        raise ValueError(f"{spec.label} is not an agent version, so it has no prompts of its own")
    return PromptDir(agents_dir() / spec.kind / "prompts")


def agent_prompts(spec: AgentSpec) -> dict[str, str]:
    """ref -> template text of the prompts `spec` renders: what its version's `prompts_in_use(params)`
    names, or all of its prompts. Empty for the engine's own kinds."""
    if not packages.is_version(spec.kind):
        return {}
    packages.mount(agents_dir())
    folder = prompt_dir(spec)
    in_use = getattr(packages.load(spec.kind), "prompts_in_use", None)
    refs = in_use(spec.params) if in_use else sorted(p.stem for p in folder.folder.glob("*.md"))
    return {ref: folder.text(ref) for ref in refs}


def new_version(parent: str) -> str:
    """Copy agent version `parent` (e.g. single_call/v1) to the architecture's next free version, without
    its configs: they stay with the version they were measured on. Returns the new version."""
    arch, _ = packages.split(parent)
    nums = [int(m.group(1)) for d in (agents_dir() / arch).iterdir() if (m := re.fullmatch(r"v(\d+)", d.name))]
    kind = f"{arch}/v{max(nums) + 1}"
    shutil.copytree(agents_dir() / parent, agents_dir() / kind,
                    ignore=shutil.ignore_patterns("configs", "__pycache__", "*.pyc"))
    (agents_dir() / kind / "configs").mkdir()
    return kind


def remove_version(kind: str) -> None:
    shutil.rmtree(agents_dir() / kind)
