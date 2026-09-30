"""Failure mining: the input for proposing challengers (docs/04-hill-climbing.md §5.2).

A bundle is built from one dev gym run, for one subject: where it loses value, its worst transcripts,
and its own prompts and settings. It holds nothing about the opponents beyond what they said in those
matches: no persona prompts, no opponent code, and nothing from a holdout run.
"""
from __future__ import annotations

from collections import defaultdict
from statistics import fmean

from pydantic import BaseModel

from regateo.agents import AgentSpec, prompts
from regateo.agents.base import prompt_refs
from regateo.agents.common import fmt_price
from regateo.core.messages import Message
from regateo.core.outcome import Outcome
from regateo.core.roles import Role, other
from regateo.storage.store import MatchRow, Store

MAX_CHARS = 240          # per message in a transcript: keeps a bundle inside a local model's context


class Bundle(BaseModel):
    run_id: str
    subject: str
    agent: dict                      # the subject's AgentSpec, as the run stored it
    prompts: dict[str, str]          # prompt ref -> template text, for the subject's own prompts only
    summary: str                     # markdown table: where value is lost, by opponent and outcome
    transcripts: list[str]

    def markdown(self) -> str:
        spec = AgentSpec.model_validate(self.agent)
        parts = [f"# Failure bundle: {spec.label} in run {self.run_id}", "",
                 "## The agent", "", f"- kind: {spec.kind}", f"- model profile: {spec.model}",
                 f"- params: {spec.params}", ""]
        for ref, text in self.prompts.items():
            parts += [f"### Prompt template `{ref}`", "", "```", text.strip(), "```", ""]
        parts += ["## Where it loses value", "", self.summary, "", "## Its worst matches", ""]
        for i, t in enumerate(self.transcripts, 1):
            parts += [f"### Match {i}", "", t, ""]
        return "\n".join(parts)


def outcome_class(o: Outcome, role: Role) -> str:
    if not o.deal:
        return f"no deal: {o.end_reason.value}"
    if o.past_reservation is role:
        return "deal past own limit"
    return "deal, they kept more" if o.share(other(role)) > o.share(role) else "deal, we kept more"


def _subject_spec(config: dict, subject: str) -> dict:
    if subject in ("a", "b"):
        return config[subject]
    return config["extra"][int(subject[1:]) - 2]


def _summary(rows: list[tuple[MatchRow, Role]]) -> str:
    cells: dict[tuple[str, str], list[float]] = defaultdict(list)
    for r, role in rows:
        assert r.outcome
        cells[(r.meta["opponent"], outcome_class(r.outcome, role))].append(r.outcome.share(role))
    by_opp: dict[str, list[float]] = defaultdict(list)
    for (opp, _), xs in cells.items():
        by_opp[opp] += xs
    lines = ["| Opponent | Outcome | Matches | Mean share |", "|---|---|---|---|"]
    for opp in sorted(by_opp, key=lambda o: fmean(by_opp[o])):
        lines.append(f"| {opp} | all | {len(by_opp[opp])} | {fmean(by_opp[opp]):.3f} |")
        for (o, cls), xs in sorted(cells.items()):
            if o == opp:
                lines.append(f"| | {cls} | {len(xs)} | {fmean(xs):.3f} |")
    return "\n".join(lines)


def _clip(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= MAX_CHARS else text[:MAX_CHARS] + "…"


def transcript(r: MatchRow, role: Role, messages: list[Message]) -> str:
    s, o = r.scenario, r.outcome
    assert o is not None
    cur = s.currency
    lines = [f"We were the **{role.value}** of {s.item}, against {r.meta['opponent']}. Our walk-away price: "
             f"{fmt_price(s.reservation(role), cur)}; theirs: {fmt_price(s.reservation(other(role)), cur)} "
             f"(we didn't know it). Market range told to both: {fmt_price(s.market_low, cur)} to "
             f"{fmt_price(s.market_high, cur)}. Deadline: {s.rules.max_rounds} messages each, "
             f"{'known' if s.rules.deadline_known else 'hidden from us'}.", ""]
    for m in messages:
        who = "us" if m.sender is role else "them"
        tags = []
        d = m.move.meta.get("decision") if m.sender is role else None
        if d:
            tags.append(d["action"] + (f" {fmt_price(d['price'], cur)}" if d.get("price") is not None else ""))
        if m.sender is role and m.move.meta.get("vetoes"):
            tags.append("vetoed first: " + "; ".join(m.move.meta["vetoes"]))
        if m.reading:
            tags.append(f"referee read: {m.reading.kind.value}"
                        + (f" {fmt_price(m.reading.price, cur)}" if m.reading.price is not None else ""))
        lines.append(f"- {m.idx + 1} {who}: {_clip(m.text)!r}" + (f"  [{' | '.join(tags)}]" if tags else ""))
    result = (f"deal at {fmt_price(o.price, cur)}" if o.deal and o.price is not None
              else f"no deal ({o.end_reason.value})")
    lines += ["", f"Result: {result}. Our share of the zone: {o.share(role):.2f}; theirs: {o.share(other(role)):.2f}."]
    return "\n".join(lines)


async def mine(store: Store, run_id: str, *, subject: str = "b", worst: int = 5) -> Bundle:
    """`subject`: a, b (the reference, default), a2... of a benchmark gym run."""
    run = await store.get_run(run_id)
    if run is None or run.kind != "gym" or run.config.get("mode") != "benchmark":
        raise ValueError(f"{run_id} is not a benchmark gym run")
    if run.config.get("purpose") == "holdout":
        raise ValueError("holdout runs are not mined: their transcripts stay unseen (docs/04-hill-climbing.md §4)")
    spec = _subject_spec(run.config, subject)
    rows = [(r, Role(r.meta["role"])) for r in await store.list_matches(run_id)
            if r.meta.get("subject") == subject and r.status == "done" and r.outcome]
    if not rows:
        raise ValueError(f"no finished matches for subject {subject!r} in {run_id}")

    # The worst matches, taken round robin across opponents so one opponent can't fill the bundle.
    by_opp: dict[str, list[tuple[MatchRow, Role]]] = defaultdict(list)
    for r, role in sorted(rows, key=lambda x: x[0].outcome.share(x[1])):  # type: ignore[union-attr]
        by_opp[r.meta["opponent"]].append((r, role))
    picked: list[tuple[MatchRow, Role]] = []
    queues = sorted(by_opp.values(), key=lambda q: q[0][0].outcome.share(q[0][1]))  # type: ignore[union-attr]
    while len(picked) < worst and any(queues):
        for q in queues:
            if q and len(picked) < worst:
                picked.append(q.pop(0))
    transcripts = [transcript(r, role, await store.match_messages(r.id)) for r, role in picked]

    agent = AgentSpec.model_validate(spec)
    own = {ref: prompts.path(ref).read_text() for ref in prompt_refs(agent) if not ref.startswith("persona_")}
    return Bundle(run_id=run_id, subject=subject, agent=spec, prompts=own, summary=_summary(rows),
                  transcripts=transcripts)
