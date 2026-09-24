"""Tournament runner.

    python -m arena.run                       # offline: full grid, template text, no API calls
    python -m arena.run --show injector       # also print one transcript
    python -m arena.run --sweep               # try many strategy settings, rank them
    python -m arena.run --llm --games 2       # use Claude for parsing and writing (needs ANTHROPIC_API_KEY)
    python -m arena.run --params '{"boulware": 4, "keep_share": 0.7}'

Score per game = share of the available surplus we captured (0 if no deal in budget).
Cells show:  deal rate  |  average score (no-deals count as 0).
"""
from __future__ import annotations

import argparse
import itertools
import json
import random
from collections import defaultdict
from dataclasses import asdict, replace
from statistics import mean

from negotiation.agent import DEFAULT_PERSONA, NegotiationAgent
from negotiation.language import DEFAULT_MODEL, TemplateWriter
from negotiation.scenario import sample_scenario
from negotiation.strategy import StrategyParams

from .match import run_match
from .opponents import SCRIPTED

# The unknown rule variants we want to be robust to.
SETTINGS = {
    "4 rnd": dict(max_rounds=4, deadline_known=True),
    "8 rnd": dict(max_rounds=8, deadline_known=True),
    "15 rnd": dict(max_rounds=15, deadline_known=True),
    "8 hidden": dict(max_rounds=8, deadline_known=False),
    "4 hidden": dict(max_rounds=4, deadline_known=False),
    "60s clock": dict(max_rounds=40, deadline_known=False, time_limit_s=60),
}
INFO_MODES = ["private", "range_hint", "full"]
OPPONENTS = list(SCRIPTED) + ["mirror"]


def make_ours(params, llm, model, text_rng):
    def factory(view, clock):
        if llm:
            from negotiation.language import LLMParser, LLMWriter
            return NegotiationAgent(view, params, LLMParser(model), LLMWriter(DEFAULT_PERSONA, model, text_rng), clock)
        return NegotiationAgent(view, params, writer=TemplateWriter(text_rng), clock=clock)
    return factory


def make_opponent(name, scenario, params, text_rng):
    def factory(view, clock):
        if name == "mirror":   # a copy of our own agent (offline text)
            return NegotiationAgent(view, params, writer=TemplateWriter(text_rng), clock=clock)
        return SCRIPTED[name](view, scenario.max_rounds, clock, text_rng)
    return factory


def evaluate(params, *, games, seed, info_modes=INFO_MODES, settings=SETTINGS,
             opponents=OPPONENTS, llm=False, model=DEFAULT_MODEL, show=None):
    """Same seed -> same scenarios for every params, so comparisons are fair."""
    master = random.Random(seed)
    stats = defaultdict(list)
    shown = False
    for info in info_modes:
        for sname, skw in settings.items():
            for opp in opponents:
                for _ in range(games):
                    g = random.Random(master.random())
                    scen = sample_scenario(g, info_mode=info, **skw)
                    our_role = g.choice(["seller", "buyer"])
                    ours = make_ours(params, llm, model, random.Random(g.random()))
                    theirs = make_opponent(opp, scen, params, random.Random(g.random()))
                    seller, buyer = (ours, theirs) if our_role == "seller" else (theirs, ours)
                    res = run_match(scen, seller, buyer, random.Random(g.random()))
                    score = scen.surplus_share(our_role, res.price) if res.deal else 0.0
                    stats[(info, sname, opp)].append((res.deal, score))
                    if show == opp and not shown:
                        shown = True
                        _print_transcript(scen, our_role, res, score)
    return stats


def _print_transcript(scen, our_role, res, score):
    print(f"\n--- example: we are the {our_role}, seller limit {scen.seller_reservation:.0f}, "
          f"buyer limit {scen.buyer_reservation:.0f}, {scen.max_rounds} rounds ---")
    for role, text in res.transcript:
        print(f"  {'US  ' if role == our_role else 'THEM'} ({role}): {text}")
    print(f"  => {'deal at ' + str(res.price) if res.deal else 'no deal'}, score {score:.2f}\n")


def summarize(stats):
    all_scores = [s for v in stats.values() for _, s in v]
    cells = [mean(s for _, s in v) for v in stats.values()]
    return mean(all_scores), min(cells)


def print_tables(stats, info_modes, settings, opponents):
    col = 13
    for info in info_modes:
        print(f"\n== info: {info} ==  (deal rate | avg score)")
        print("opponent".ljust(11) + "".join(s.rjust(col) for s in settings))
        for opp in opponents + ["ALL"]:
            row = opp.ljust(11)
            for s in settings:
                v = [x for o in opponents for x in stats[(info, s, o)]] if opp == "ALL" else stats[(info, s, opp)]
                row += f"{100 * mean(d for d, _ in v):4.0f}% | {mean(x for _, x in v):.2f}".rjust(col)
            print(row)
    overall, worst = summarize(stats)
    print(f"\nOVERALL avg score {overall:.3f}   worst cell {worst:.3f}")


def sweep(base, games, seed):
    grid = dict(boulware=[1.5, 3.0, 5.0], keep_share=[0.5, 0.65, 0.8],
                close_by=[0.7, 0.85], assumed_rounds=[3, 4, 6])
    results = []
    for combo in itertools.product(*grid.values()):
        p = replace(base, **dict(zip(grid, combo)))
        overall, worst = summarize(evaluate(p, games=games, seed=seed))
        results.append((overall, worst, dict(zip(grid, combo))))
    results.sort(key=lambda r: r[0], reverse=True)
    print("avg    worst  params")
    for overall, worst, p in results[:10]:
        print(f"{overall:.3f}  {worst:.3f}  {p}")
    print("...\nbottom 3:")
    for overall, worst, p in results[-3:]:
        print(f"{overall:.3f}  {worst:.3f}  {p}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=40, help="games per table cell")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--params", type=str, default="{}", help="JSON overrides for StrategyParams")
    ap.add_argument("--llm", action="store_true", help="use Claude for parsing and writing")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--show", choices=OPPONENTS, help="print one transcript against this opponent")
    ap.add_argument("--sweep", action="store_true")
    args = ap.parse_args()

    params = replace(StrategyParams(), **json.loads(args.params))
    if args.sweep:
        sweep(params, games=max(args.games // 3, 5), seed=args.seed)
        return
    print("params:", asdict(params))
    stats = evaluate(params, games=args.games, seed=args.seed, llm=args.llm, model=args.model, show=args.show)
    print_tables(stats, INFO_MODES, list(SETTINGS), OPPONENTS)


if __name__ == "__main__":
    main()
