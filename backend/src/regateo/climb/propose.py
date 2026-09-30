"""The proposer: one structured call to a local model turns a failure bundle into challengers
(docs/04-hill-climbing.md §5.2). Code then validates each proposal and writes it as an agent config
(plus a new prompt version when it rewrites the prompt), a screen gym config and an experiment stub.

The model only ever sees the bundle, the experiment log and its own instructions, so what it can
learn about the opponents is limited to what they said in dev matches.
"""
from __future__ import annotations

import hashlib
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
from regateo.storage.store import Store

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
    accept_words: Literal["reader", "strict"] | None = None
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
    """What was tried already: the learnings from before the baseline, the experiment log in the docs,
    and every climb round's results."""
    parts = []
    learnings = REPO_DIR / "docs" / "05-learnings.md"
    if learnings.exists():
        parts.append(learnings.read_text().strip())
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
    params = {k: v for k in ("analysis", "state_digest", "fence", "checks", "accept_words")
              if (v := getattr(p, k)) is not None}
    return {"params": params, **({"model": p.model} if p.model else {}),
            **({"prompt_edit": p.prompt_edit.model_dump()} if p.prompt_edit else {})}


def _brief(p: Proposal, prompt_file: str | None = None) -> dict:
    """`_changes` for a table or log: a rewrite of the whole prompt shows as its new file, not its text."""
    ch = _changes(p)
    edit = ch.get("prompt_edit")
    if edit and len(edit["find"]) > 500:
        ch["prompt_edit"] = f"prompt rewritten: {prompt_file or 'new version'}"
    return ch


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
    if (p.checks or p.accept_words) and parent.kind not in ("o1", "o2"):
        reasons.append(f"code vetoes need an o1 or o2 parent, not {parent.kind}")
    reasons += edited_prompt(p, parent)[1]
    return reasons


def behaviour_key(spec: AgentSpec) -> str:
    """What an agent does, independent of names: its kind, model profile, settings and the text of its
    prompts, but not which file a prompt is in. A proposal that copies an earlier agent under a new name,
    or saves an earlier prompt as a new version, gets the same key."""
    config = spec.ref().config
    body = {**config, "params": {k: v for k, v in config["params"].items() if k != "prompt"},
            "prompts": sorted(config.get("prompts", {}).values())}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()[:16]


async def known_agents(store: Store) -> dict[str, str]:
    """Every agent our gym runs have measured, by behaviour key: "<label> in <run name> (<run id>)"."""
    known: dict[str, str] = {}
    for run in reversed(await store.list_runs("gym", limit=10000)):
        specs = [run.config.get("a"), run.config.get("b"), *run.config.get("extra", [])]
        for raw in filter(None, specs):
            try:
                spec = AgentSpec.model_validate(raw)
                known.setdefault(behaviour_key(spec), f"{spec.label} in {run.name} ({run.id})")
            except Exception:                        # e.g. a prompt file that no longer exists
                continue
    return known


def _next_prompt_version(family: str) -> str:
    versions = [int(m.group(1)) for f in prompts.path(f"{family}.v1").parent.glob(f"{family}.v*.md")
                if (m := re.search(r"\.v(\d+)\.md$", f.name))]
    return f"{family}.v{max(versions, default=0) + 1}"


def write(proposals: list[Proposal], parent_name: str, source: str = "the climb loop (regateo propose)",
          known: dict[str, str] | None = None) -> tuple[list[Written], list[Rejected]]:
    """Validate, then write an agent config per good proposal (configs/agents/<kind>/<name>.yaml).
    `known` (from `known_agents`): a proposal that behaves exactly like an agent already measured, or
    like an earlier proposal in this batch, is rejected and its files removed."""
    parent = AgentSpec.resolve(parent_name)
    known = {behaviour_key(parent): f"the parent, {parent_name}", **(known or {})}
    written, rejected = [], []
    for p in proposals:
        vetoed = p.checks or p.accept_words
        folder = configs_dir() / "agents" / ("o2" if vetoed else parent.kind)
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
        if vetoed and parent.kind == "o1":
            data["kind"] = "o2"
        if p.model:
            data["model"] = p.model
        if params:
            data["params"] = params
        folder.mkdir(parents=True, exist_ok=True)
        header = (f"# Proposed by {source}. Targets: {' '.join(p.failure.split())}\n"
                  f"# Hypothesis: {' '.join(p.hypothesis.split())}\n")
        (folder / f"{p.name}.yaml").write_text(header + yaml.safe_dump(data, sort_keys=False, width=1000))
        agent = f"{folder.name}/{p.name}"
        spec = AgentSpec.resolve(agent)
        prompt_refs(spec)                                    # fails loudly if a prompt ref is broken
        key = behaviour_key(spec)
        if key in known:
            (folder / f"{p.name}.yaml").unlink()
            if prompt_file:
                (prompts.path(f"{family}.v1").parent / prompt_file).unlink()
            rejected.append(Rejected(proposal=p, reasons=[f"behaves exactly like {known[key]}"]))
            continue
        known[key] = f"{agent}, proposed in this batch"
        written.append(Written(proposal=p, agent=agent, prompt_file=prompt_file))
    return written, rejected


def next_experiment() -> tuple[int, Path]:
    folder = REPO_DIR / "docs" / "experiments"
    nums = [int(m.group(1)) for f in folder.glob("*.md") if (m := re.match(r"(\d{3})-", f.name))]
    return max(nums, default=0) + 1, folder


def write_experiment(written: list[Written], *, reference: str, bench: str, source_run: str,
                     by: str = "the climb loop (`regateo propose`, local Qwen)") -> str:
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
    rows = "\n".join(f"| {w.agent} | {_brief(w.proposal, w.prompt_file)} | {' '.join(w.proposal.hypothesis.split())} |"
                     for w in written)
    (folder / f"{num:03d}-climb.md").write_text(
        f"# {num:03d}: Climb round from {reference}\n\n"
        f"**Bench:** {bench}, successive halving to the full bench. **Reference:** {reference}. "
        f"**Config:** `backend/configs/gym/{name}.yaml`.\n\n"
        f"Proposed by {by} from the failures in {source_run}. "
        "Not yet reviewed by a person.\n\n"
        "## Variants\n\n| Challenger | Change | Hypothesis |\n|---|---|---|\n" + rows + "\n\n## Results\n\n(pending)\n")
    return name


def log(written: list[Written], results: dict[str, str] | None = None) -> None:
    log_path().parent.mkdir(parents=True, exist_ok=True)
    with log_path().open("a") as f:
        for w in written:
            f.write(json.dumps({"agent": w.agent, "hypothesis": " ".join(w.proposal.hypothesis.split()),
                                "changes": _brief(w.proposal, w.prompt_file),
                                "result": (results or {}).get(w.agent, "pending")}) + "\n")
