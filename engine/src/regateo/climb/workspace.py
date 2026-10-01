"""A workspace for an agentic proposer, e.g. Claude Code in a sandbox (docs/04-hill-climbing.md §5.2).

`export` writes a folder holding only what the proposer may see (§5.3): our agent's config and prompts,
every match our agents played in the given dev runs (both sides' messages, both limits after the fact,
the referee's readings, our vetoes), the runs' reports, and what was tried already. No persona prompts,
no opponent or referee code, no bench files, nothing from a holdout run. The proposer writes candidates
into `candidates/`, and `adopt` validates them and turns them into agent configs, like `regateo propose`.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from regateo.agents import AgentSpec, prompts
from regateo.agents.base import prompt_refs
from regateo.cli import format as fmt
from regateo.climb.propose import PromptEdit, Proposal, Rejected, Written, tried, write
from regateo.core.roles import Role, other
from regateo.gym import build_gym_report
from regateo.storage.store import Store

LEVERS = ("analysis", "state_digest", "fence", "checks", "accept_words", "model")


def _match(r, role: Role, messages, run_id: str, label: str) -> dict:
    s, o = r.scenario, r.outcome
    return {
        "run": run_id, "pair": r.meta["pair"], "agent": label, "opponent": r.meta["opponent"], "role": role.value,
        "cell": r.meta["cell"], "item": s.item, "currency": s.currency,
        "our_limit": s.reservation(role), "their_limit": s.reservation(other(role)),
        "market_low": s.market_low, "market_high": s.market_high,
        "max_rounds": s.rules.max_rounds, "deadline_known": s.rules.deadline_known,
        "result": {"deal": o.deal, "price": o.price, "end": o.end_reason.value, "our_share": round(o.share(role), 4),
                   "their_share": round(o.share(other(role)), 4), "past_our_limit": o.past_reservation is role},
        "messages": [{
            "n": m.idx + 1, "from": "us" if m.sender is role else "them", "text": m.text,
            **({"our_decision": m.move.meta["decision"]} if m.sender is role and m.move.meta.get("decision") else {}),
            **({"vetoed_first": m.move.meta["vetoes"]} if m.sender is role and m.move.meta.get("vetoes") else {}),
            **({"repaired": True} if m.sender is role and m.move.meta.get("repaired") else {}),
            **({"referee_read": {"kind": m.reading.kind.value, "price": m.reading.price}} if m.reading else {}),
        } for m in messages],
    }


META = ".regateo.json"          # which parent and runs a workspace was made from, for `adopt`


async def export(store: Store, runs: list[str], parent: str, out: Path) -> Path:
    _prepare(out, parent)
    for run_id in runs:
        run = await store.get_run(run_id)
        if run is None or run.kind != "gym" or run.config.get("mode") != "benchmark":
            raise ValueError(f"{run_id} is not a benchmark gym run")
        if run.config.get("purpose") == "holdout":
            raise ValueError(f"{run_id} is a holdout run: its transcripts stay unseen (docs/04-hill-climbing.md §4)")
        report = await build_gym_report(store, run_id)
        labels = {"a": report.a.label, "b": report.b.label,
                  **{f"a{n}": AgentSpec.model_validate(s).label
                     for n, s in enumerate(run.config.get("extra", []), start=2)}}
        matches = [_match(r, Role(r.meta["role"]), await store.match_messages(r.id), run_id,
                          labels.get(r.meta["subject"], r.meta["subject"]))
                   for r in await store.list_matches(run_id) if r.status == "done" and r.outcome]
        _write_run(out / "data" / run_id, fmt.gym_report(report), matches)
    _finish(out, parent, runs)
    return out


def _prepare(out: Path, parent: str) -> None:
    if out.exists() and any(out.iterdir()):
        raise ValueError(f"{out} is not empty")
    spec = AgentSpec.resolve(parent)
    (out / "agent" / "prompts").mkdir(parents=True)
    (out / "candidates").mkdir()
    (out / "agent" / "config.yaml").write_text(yaml.safe_dump(
        {"name": parent, "kind": spec.kind, "model": spec.model, "params": spec.params}, sort_keys=False))
    for ref in prompt_refs(spec):
        if not ref.startswith("persona_"):
            shutil.copy(prompts.path(ref), out / "agent" / "prompts" / f"{ref}.md")


def _write_run(folder: Path, report: str, matches: list[dict]) -> None:
    folder.mkdir(parents=True)
    (folder / "report.txt").write_text(report)
    (folder / "matches.jsonl").write_text("".join(json.dumps(m) + "\n" for m in matches))


def _finish(out: Path, parent: str, runs: list[str]) -> None:
    (out / "data" / "tried.md").write_text(tried())
    (out / "README.md").write_text(_task(parent, runs))
    (out / META).write_text(json.dumps({"parent": parent, "runs": runs}))


def workspace_meta(folder: Path) -> dict:
    path = folder / META
    if not path.exists():
        raise ValueError(f"{folder} is not a proposer workspace (no {META})")
    return json.loads(path.read_text())


class Candidate(BaseModel):
    failure: str
    hypothesis: str
    changes: dict = Field(default_factory=dict)       # levers: analysis, state_digest, fence, checks, ...
    prompt: str | None = None                         # file in the candidate folder: a new version of the prompt


def adopt(folder: Path, parent: str | None = None,
          known: dict[str, str] | None = None) -> tuple[list[Written], list[Rejected]]:
    """Turn `candidates/<name>/candidate.yaml` (plus an optional new prompt) into agent configs.
    `parent` defaults to the agent the workspace was made from."""
    parent = parent or workspace_meta(folder)["parent"]
    spec = AgentSpec.resolve(parent)
    old = prompts.path(spec.params.get("prompt", "negotiator_system.v1")).read_text()
    proposals, rejected = [], []
    for d in sorted(p for p in (folder / "candidates").iterdir() if p.is_dir()):
        try:
            c = Candidate.model_validate(yaml.safe_load((d / "candidate.yaml").read_text()))
            unknown = sorted(set(c.changes) - set(LEVERS))
            if unknown:
                raise ValueError(f"unknown levers {unknown}; known: {list(LEVERS)}")
            edit = None
            if c.prompt:
                new = (d / c.prompt).read_text()
                edit = PromptEdit(find=old, replace=new) if new.strip() != old.strip() else None
            proposals.append(Proposal(name=d.name, failure=c.failure, hypothesis=c.hypothesis, prompt_edit=edit,
                                      **c.changes))
        except Exception as e:                          # a bad candidate is dropped, not repaired
            rejected.append(Rejected(proposal=Proposal(name=d.name, failure="?", hypothesis="?"), reasons=[str(e)]))
    written, bad = write(proposals, parent, source="an agentic proposer (regateo workspace)", known=known)
    return written, rejected + bad


def _task(parent: str, runs: list[str]) -> str:
    return f"""# Improve a negotiating agent

You are improving an AI agent that negotiates the price of one item against another AI agent, as buyer or seller,
in free text. Your job: study how it plays, find where it loses value, and propose challengers that each change one
idea. They will be measured on the same benchmark, paired against the current agent ({parent}), and the best one
must then also win on a benchmark you can't see. So propose ideas that should hold against any opponent, not
tricks that fit the opponents in this data.

## How it is scored

- **Share**: the fraction of the zone of possible agreement the agent keeps. With walk-away prices L (ours) and T
  (theirs), a deal at L scores 0 and a deal at T scores 1. No deal scores 0. A deal past our own walk-away price
  is a loss, and it disqualifies a challenger outright.
- Each agent knows only its own walk-away price. `their_limit` in the data is there for your analysis only.
- A challenger also must not close deals noticeably less often than the current agent.
- Opponents will be stronger and more varied in the real tournament. Rules that a strong, adaptive opponent could
  learn and exploit (fixed concession schedules, "always accept in the last round") are likely to fail there.
  Prefer changes that make the model reason better over rules that decide for it.

## How the agent works

`agent/config.yaml` and `agent/prompts/`. Each turn, one LLM call (local Qwen, 27B) gets the system prompt (the
template in `agent/prompts/negotiator_system.*.md`, with `$placeholders` filled in per match) and the conversation
so far, and answers with JSON: `action` (offer, accept, reject, message, walk_away), `price`, and `message` (what the
other side reads). The referee reads the message text, so the message is what counts.

The agent kind is `{AgentSpec.resolve(parent).kind}`. For kind o2, code checks each decision before it is sent
(`checks` below); a decision that fails gets one retry with feedback, then is replaced by a safe move. In the data,
`vetoed_first` shows what failed, and `repaired` that the safe move was sent.

## The data

- `data/<run>/report.txt`: each run's report: every agent in it against the reference, by opponent, role and cell.
- `data/<run>/matches.jsonl`: one line per match one of our agents played: the scenario, both walk-away prices,
  the result, and every message with our decision, vetoes and how the referee read it. Several of our agents
  played the same pairs (same `pair`: same scenario, opponent, role and seed), so you can compare them directly.
- `data/tried.md`: experiments and climb rounds already run, and their results. Don't repeat them unless you say
  why a variation is worth it.

You may write scripts to analyse the data. Don't look for anything outside this folder.

## What to deliver

Up to 8 challengers, each in `candidates/<name>/` (name: a short slug, lowercase letters, digits and dashes):

- `candidate.yaml`:
  ```yaml
  failure: the pattern it targets, with evidence (runs, pairs, counts)
  hypothesis: what will improve and why; what result would prove it wrong
  changes: {{}}              # levers, optional (below)
  prompt: prompt.md        # optional: a new version of the prompt template
  ```
- `prompt.md`, optional: a complete new version of `agent/prompts/negotiator_system.*.md`. Keep every `$placeholder`
  exactly as it is and add no new ones. Write no other `$` sign: "USD 150", or no number at all.

Levers for `changes`:
- `analysis: true`: the model writes private notes before each decision.
- `state_digest: true`: a private summary of the offers so far is added to each turn; `moves` leaves out how their
  offer compares with the walk-away price.
- `fence: true`: the other side's messages are wrapped in random tags, against injected instructions.
- `checks`: code veto: `limit` (never offer or accept past the walk-away price), `limit+mentions` (also never write
  a price past it), `all` (also no walking back offers, no prices other than ours and theirs).
- `accept_words`: code veto on a message that doesn't accept but may read as accepting: `reader` or `strict`.
- `model`: `qwen-local` (default), `qwen-local-think` (reasons before answering; slower), `qwen-local-pp0`.

Each challenger should change one idea, so its result says whether that idea works. A prompt rewrite may touch
several passages if they serve one idea. Finish with a short `candidates/SUMMARY.md`: what you found in the data,
ranked by how much value it costs, and which candidate targets what.

Data from runs: {", ".join(runs)}.
"""
