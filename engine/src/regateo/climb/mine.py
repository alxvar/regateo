"""Failure mining: the input for proposing challengers (docs/04-hill-climbing.md §5.2).

A bundle is built from one dev gym run, for one subject: where it loses value, the matches where it lost
most against what another of our agents got in the same pair (its regret), and its own prompts and
settings. Ranking by regret, not by share, skips matches nobody could win, such as a narrow zone against
a hardliner, and shows next to each what the better agent did. It holds nothing about the opponents
beyond what they said in those matches: no persona prompts, no opponent code, and nothing from a holdout run.
"""
from __future__ import annotations

from collections import defaultdict
from statistics import fmean

from pydantic import BaseModel

from regateo.agents import AgentSpec
from regateo.climb.versions import agent_prompts
from regateo.core.messages import Message
from regateo.core.outcome import Outcome
from regateo.core.roles import Role, other
from regateo.opponents.common import fmt_price
from regateo.storage.store import MatchRow, Store

MAX_CHARS = 240          # per message in a transcript: keeps a bundle inside a local model's context
CONTRAST = 2             # the top matches also get the better agent's transcript of the same pair


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
        parts += ["## Where it loses value", "", self.summary, "",
                  "## Its worst matches", "",
                  "Ranked by regret: how much less it got than the best of our other agents in the same pair "
                  "(same scenario, opponent, role and seed). Some also show what that agent did.", ""]
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


def _summary(rows: list[tuple[MatchRow, Role]], regret: dict[str, float]) -> str:
    cells: dict[tuple[str, str], list[float]] = defaultdict(list)
    regrets: dict[str, list[float]] = defaultdict(list)
    for r, role in rows:
        assert r.outcome
        cells[(r.meta["opponent"], outcome_class(r.outcome, role))].append(r.outcome.share(role))
        if r.meta["pair"] in regret:
            regrets[r.meta["opponent"]].append(regret[r.meta["pair"]])
    by_opp: dict[str, list[float]] = defaultdict(list)
    for (opp, _), xs in cells.items():
        by_opp[opp] += xs
    lines = ["| Opponent | Outcome | Matches | Mean share | Mean regret |", "|---|---|---|---|---|"]
    for opp in sorted(by_opp, key=lambda o: fmean(by_opp[o])):
        reg = f"{fmean(regrets[opp]):.3f}" if regrets[opp] else "-"
        lines.append(f"| {opp} | all | {len(by_opp[opp])} | {fmean(by_opp[opp]):.3f} | {reg} |")
        for (o, cls), xs in sorted(cells.items()):
            if o == opp:
                lines.append(f"| | {cls} | {len(xs)} | {fmean(xs):.3f} | |")
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
    by_pair: dict[str, dict[str, tuple[MatchRow, Role]]] = defaultdict(dict)
    for r in await store.list_matches(run_id):
        if r.status == "done" and r.outcome:
            by_pair[r.meta["pair"]][r.meta["subject"]] = (r, Role(r.meta["role"]))
    rows = [g[subject] for g in by_pair.values() if subject in g]
    if not rows:
        raise ValueError(f"no finished matches for subject {subject!r} in {run_id}")

    # Regret per pair: the best share another subject got there, minus ours. Without other subjects, or
    # where nobody did better, a match falls back to its share, after every match with regret.
    def share(x: tuple[MatchRow, Role]) -> float:
        return x[0].outcome.share(x[1])  # type: ignore[union-attr]

    # A deal past either side's limit doesn't count as doing better: it is a misread or a loss, not a lesson.
    best: dict[str, tuple[str, float]] = {}
    for pair, g in by_pair.items():
        others = [(s, share(x)) for s, x in g.items()
                  if s != subject and x[0].outcome.past_reservation is None]  # type: ignore[union-attr]
        if subject in g and others:
            best[pair] = max(others, key=lambda o: o[1])
    regret = {pair: sh - share(by_pair[pair][subject]) for pair, (_, sh) in best.items()}

    def rank(x: tuple[MatchRow, Role]) -> tuple[bool, float]:
        reg = regret.get(x[0].meta["pair"], 0.0)
        return (reg <= 0, -reg if reg > 0 else share(x))

    # Taken round robin across opponents so one opponent can't fill the bundle.
    by_opp: dict[str, list[tuple[MatchRow, Role]]] = defaultdict(list)
    for r, role in sorted(rows, key=rank):
        by_opp[r.meta["opponent"]].append((r, role))
    picked: list[tuple[MatchRow, Role]] = []
    queues = sorted(by_opp.values(), key=lambda q: rank(q[0]))
    while len(picked) < worst and any(queues):
        for q in queues:
            if q and len(picked) < worst:
                picked.append(q.pop(0))

    labels = _labels(run.config)
    transcripts = []
    for n, (r, role) in enumerate(picked):
        text = transcript(r, role, await store.match_messages(r.id))
        pair = r.meta["pair"]
        if regret.get(pair, 0.0) > 0:
            other_subject, other_share = best[pair]
            text = (f"Regret {regret[pair]:.2f}: {labels.get(other_subject, other_subject)} got {other_share:.2f} "
                    f"in the same pair.\n\n{text}")
            if n < CONTRAST:
                orow, orole = by_pair[pair][other_subject]
                text += (f"\n\n#### What {labels.get(other_subject, other_subject)} did in the same pair\n\n"
                         + transcript(orow, orole, await store.match_messages(orow.id)))
        transcripts.append(text)

    agent = AgentSpec.model_validate(spec)
    own = agent_prompts(agent)
    return Bundle(run_id=run_id, subject=subject, agent=spec, prompts=own, summary=_summary(rows, regret),
                  transcripts=transcripts)


def _labels(config: dict) -> dict[str, str]:
    specs = {"a": config["a"], "b": config["b"], **{f"a{n}": s for n, s in enumerate(config.get("extra", []), 2)}}
    return {k: AgentSpec.model_validate(v).label for k, v in specs.items()}
