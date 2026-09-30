"""The proposer: one structured call to a local model turns a failure bundle into challengers
(docs/04-hill-climbing.md §5.2). Code then validates each proposal and writes it as an agent config
(plus a new prompt version when it rewrites the prompt), a screen gym config and an experiment stub.

The model only ever sees the bundle, the experiment log and its own instructions, so what it can
learn about the opponents is limited to what they said in dev matches.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from string import Template
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from regateo.agents import AgentSpec, prompts
from regateo.agents.base import prompt_refs
from regateo.climb.mine import Bundle
from regateo.core.config import REPO_DIR, configs_dir, data_dir
from regateo.llm.client import LLMClient
from regateo.llm.types import ChatMessage, LLMRequest

PROPOSER_PROMPT = "proposer_system.v1"
MODELS = ("qwen-local", "qwen-local-think", "qwen-local-pp0")
TRIED_MAX = 15                        # latest climb results shown to the proposer: its context is small
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")


class PromptEdit(BaseModel):
    find: str = Field(description="exact passage of the current prompt to replace; empty to add a new rule at the end")
    replace: str = Field(description="the new text")


class Proposal(BaseModel):
    name: str = Field(description="short slug: lowercase letters, digits and dashes")
    failure: str = Field(description="the failure pattern it targets, quoting the bundle")
    hypothesis: str = Field(description="what will improve, and why")
    prompt_edit: PromptEdit | None = Field(default=None, description="one edit to the prompt, or null")
    analysis: bool | None = None
    state_digest: bool | None = None
    fence: bool | None = None
    checks: Literal["limit", "limit+mentions", "all"] | None = None
    model: Literal["qwen-local", "qwen-local-think", "qwen-local-pp0"] | None = None


class Proposals(BaseModel):
    proposals: list[Proposal]


class Rejected(BaseModel):
    proposal: Proposal
    reasons: list[str]


class Written(BaseModel):
    proposal: Proposal
    agent: str                        # config name, e.g. o2/firm-close
    prompt_file: str | None = None


def log_path() -> Path:
    return data_dir() / "climb" / "log.jsonl"


def tried() -> str:
    """What was tried already: the experiment log in the docs, and every climb round's results."""
    parts = []
    readme = REPO_DIR / "docs" / "experiments" / "README.md"
    if readme.exists() and "## Log" in (text := readme.read_text()):
        parts.append(text.split("## Log", 1)[1].strip())
    if log_path().exists():
        rows = [json.loads(line) for line in log_path().read_text().splitlines() if line.strip()]
        parts += [f"- {r['agent']}: {r['hypothesis']} Changes: {r['changes']}. Result: {r.get('result', 'pending')}"
                  for r in rows[-TRIED_MAX:]]
    return "\n".join(parts) or "Nothing yet."


async def ask(llm: LLMClient, bundle: Bundle, *, n: int = 3) -> list[Proposal]:
    resp = await llm.complete(LLMRequest(
        system=prompts.render(PROPOSER_PROMPT, n=n),
        messages=[ChatMessage(role="user", content=f"{bundle.markdown()}\n\n# Already tried\n\n{tried()}")],
        output_schema=Proposals, tags={"stage": "proposer"}))
    assert isinstance(resp.parsed, Proposals)
    return resp.parsed.proposals


def _escape(text: str) -> str:
    """A literal "$150" would break string.Template: write it as "$$150"."""
    return re.sub(r"\$(?=[\d.,])", "$$", text)


def _changes(p: Proposal) -> dict:
    params = {k: v for k in ("analysis", "state_digest", "fence", "checks") if (v := getattr(p, k)) is not None}
    return {"params": params, **({"model": p.model} if p.model else {}),
            **({"prompt_edit": p.prompt_edit.model_dump()} if p.prompt_edit else {})}


def edited_prompt(p: Proposal, parent: AgentSpec) -> tuple[str | None, list[str]]:
    """The parent's prompt template with the proposal's edit applied, or the reasons it can't be."""
    if not p.prompt_edit:
        return None, []
    old = prompts.path(parent.params.get("prompt", "negotiator_system.v1")).read_text()
    edit = p.prompt_edit
    if not edit.replace.strip():
        return None, ["the prompt edit's replacement is empty"]
    if edit.find.strip():
        n = old.count(edit.find)
        if n != 1:
            return None, [f"the prompt edit's passage occurs {n} times in the prompt, not once"]
        new = old.replace(edit.find, _escape(edit.replace))
    else:
        new = old.rstrip("\n") + "\n" + _escape(edit.replace).strip() + "\n"
    got = Template(new)
    if not got.is_valid():
        return None, ["the edit has a stray $ that isn't a placeholder"]
    want, have = set(Template(old).get_identifiers()), set(got.get_identifiers())
    if have != want:
        return None, [f"prompt placeholders differ: missing {sorted(want - have)}, unknown {sorted(have - want)}"]
    return new, []


def validate(p: Proposal, parent: AgentSpec, taken: set[str]) -> list[str]:
    reasons = []
    if not _SLUG.match(p.name):
        reasons.append(f"name {p.name!r} is not a short slug")
    if p.name in taken:
        reasons.append(f"name {p.name!r} is taken")
    ch = _changes(p)
    if not ch["params"] and "model" not in ch and "prompt_edit" not in ch:
        reasons.append("changes nothing")
    if p.model and p.model == parent.model:
        reasons.append(f"model is already {p.model}")
    if p.checks and parent.kind not in ("o1", "o2"):
        reasons.append(f"checks need an o1 or o2 parent, not {parent.kind}")
    reasons += edited_prompt(p, parent)[1]
    return reasons


def _next_prompt_version(family: str) -> str:
    versions = [int(m.group(1)) for f in prompts.path(f"{family}.v1").parent.glob(f"{family}.v*.md")
                if (m := re.search(r"\.v(\d+)\.md$", f.name))]
    return f"{family}.v{max(versions, default=0) + 1}"


def write(proposals: list[Proposal], parent_name: str) -> tuple[list[Written], list[Rejected]]:
    """Validate, then write an agent config per good proposal (configs/agents/<kind>/<name>.yaml)."""
    parent = AgentSpec.resolve(parent_name)
    written, rejected = [], []
    for p in proposals:
        folder = configs_dir() / "agents" / ("o2" if p.checks else parent.kind)
        taken = {f.stem for f in folder.glob("*.yaml")} | {w.proposal.name for w in written}
        if reasons := validate(p, parent, taken):
            rejected.append(Rejected(proposal=p, reasons=reasons))
            continue
        ch = _changes(p)
        params = dict(ch["params"])
        prompt_file = None
        text, _ = edited_prompt(p, parent)
        if text is not None:
            family = re.sub(r"\.v\d+$", "", parent.params.get("prompt", "negotiator_system"))
            ref = _next_prompt_version(family)
            path = prompts.path(f"{family}.v1").parent / f"{ref}.md"
            path.write_text(text)
            params["prompt"] = ref
            prompt_file = path.name
        data: dict = {"extends": parent_name}
        if p.checks and parent.kind == "o1":
            data["kind"] = "o2"
        if p.model:
            data["model"] = p.model
        if params:
            data["params"] = params
        folder.mkdir(parents=True, exist_ok=True)
        header = (f"# Proposed by the climb loop (regateo propose). Targets: {' '.join(p.failure.split())}\n"
                  f"# Hypothesis: {' '.join(p.hypothesis.split())}\n")
        (folder / f"{p.name}.yaml").write_text(header + yaml.safe_dump(data, sort_keys=False, width=1000))
        agent = f"{folder.name}/{p.name}"
        spec = AgentSpec.resolve(agent)
        prompt_refs(spec)                                    # fails loudly if a prompt ref is broken
        written.append(Written(proposal=p, agent=agent, prompt_file=prompt_file))
    return written, rejected


def next_experiment() -> tuple[int, Path]:
    folder = REPO_DIR / "docs" / "experiments"
    nums = [int(m.group(1)) for f in folder.glob("*.md") if (m := re.match(r"(\d{3})-", f.name))]
    return max(nums, default=0) + 1, folder


def write_experiment(written: list[Written], *, reference: str, bench: str, source_run: str) -> str:
    """A gym config (the full bench, with successive halving and early stopping) and an experiment stub
    for one round. Returns the gym config name."""
    num, folder = next_experiment()
    name = f"exp-{num:03d}-climb"
    gym = {"name": name, "bench": bench, "reference": reference,
           "challengers": [w.agent for w in written], "halving": True, "early_stop": True,
           "settings": {"concurrency": 32, "cache": "readwrite"}}
    (configs_dir() / "gym" / f"{name}.yaml").write_text(
        f"# Climb round (docs/experiments/{num:03d}-climb.md), proposed from {source_run}.\n"
        + yaml.safe_dump(gym, sort_keys=False))
    rows = "\n".join(f"| {w.agent} | {_changes(w.proposal)} | {' '.join(w.proposal.hypothesis.split())} |"
                     for w in written)
    (folder / f"{num:03d}-climb.md").write_text(
        f"# {num:03d}: Climb round from {reference}\n\n"
        f"**Bench:** {bench}, successive halving to the full bench. **Reference:** {reference}. "
        f"**Config:** `backend/configs/gym/{name}.yaml`.\n\n"
        f"Proposed by the climb loop (`regateo propose`, local Qwen) from the failures in {source_run}. "
        "Not yet reviewed by a person.\n\n"
        "## Variants\n\n| Challenger | Change | Hypothesis |\n|---|---|---|\n" + rows + "\n\n## Results\n\n(pending)\n")
    return name


def log(written: list[Written], results: dict[str, str] | None = None) -> None:
    log_path().parent.mkdir(parents=True, exist_ok=True)
    with log_path().open("a") as f:
        for w in written:
            f.write(json.dumps({"agent": w.agent, "hypothesis": " ".join(w.proposal.hypothesis.split()),
                                "changes": _changes(w.proposal),
                                "result": (results or {}).get(w.agent, "pending")}) + "\n")
