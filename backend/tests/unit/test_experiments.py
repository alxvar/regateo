import pytest

from regateo.arena import ArenaSpec, build_arena_report, run_arena
from regateo.gym import GymSpec, build_gym_report, run_gym
from regateo.storage import Store

SCEN = {"per_cell": 6, "max_rounds": [4, 8]}


def gym(mode, **kw):
    base = {"name": "t", "mode": mode, "a": "boulware", "b": {"kind": "boulware", "name": "soft",
            "params": {"boulware": 1.5}}, "scenarios": SCEN, "sim_clock": True, "seed": 3}
    return GymSpec.model_validate({**base, **kw})


def test_duel_jobs_swap_roles_on_same_scenario():
    jobs = gym("duel").jobs()
    assert len(jobs) == 2 * 12
    a, b = jobs[0], jobs[1]
    assert a.scenario == b.scenario and a.seed == b.seed
    assert a.seller.label == b.buyer.label == "boulware"


def test_benchmark_jobs_are_paired():
    jobs = gym("benchmark", opponents=["scripted:linear", "scripted:liar"]).jobs()
    assert len(jobs) == 12 * 2 * 2 * 2            # scenarios x opponents x roles x subjects
    by_pair = {}
    for j in jobs:
        by_pair.setdefault(j.meta["pair"], []).append(j)
    for pair in by_pair.values():
        x, y = pair
        assert x.seed == y.seed and x.scenario == y.scenario and {x.meta["subject"], y.meta["subject"]} == {"a", "b"}


def test_same_agent_rejected():
    with pytest.raises(ValueError):
        GymSpec.model_validate({"name": "t", "a": "boulware", "b": "boulware"}).jobs()


async def test_gym_end_to_end(tmp_path):
    store = await Store.open(tmp_path / "db")
    run_id, summary = await run_gym(gym("benchmark", opponents=["scripted:hardliner", "scripted:pushover"]), store)
    assert summary.done == summary.total == 96
    r = await build_gym_report(store, run_id)
    assert r.status == "done" and r.diff.n == 48 and r.a.label == "boulware" and r.b.label == "soft"
    assert {b.key for b in r.by_opponent} == {"scripted:hardliner", "scripted:pushover"}
    assert r.a.past_reservation == 0 and 0 < r.a.mean_share.mean < 1


async def test_duel_report(tmp_path):
    store = await Store.open(tmp_path / "db")
    run_id, _ = await run_gym(gym("duel"), store)
    r = await build_gym_report(store, run_id)
    assert r.diff.n == 12 and r.by_opponent == []
    # duel shares are complementary on deals: A + B == 1 per deal match on average over the pair
    assert abs(r.a.mean_share.mean + r.b.mean_share.mean - r.a.deal_rate.mean) < 1e-9


async def test_arena_end_to_end(tmp_path):
    spec = ArenaSpec.model_validate({"name": "t", "roster": ["boulware", "scripted:pushover", "scripted:hardliner"],
                                     "games_per_pair": 5, "scenarios": SCEN, "sim_clock": True})
    assert len(spec.jobs()) == 3 * 5 * 2
    store = await Store.open(tmp_path / "db")
    run_id, _ = await run_arena(spec, store)
    r = await build_arena_report(store, run_id)
    assert [s.rank for s in r.leaderboard] == [1, 2, 3] and r.leaderboard[-1].label == "scripted:pushover"
    assert len(r.matrix) == 6 and all(c.n == 10 for c in r.matrix)


def test_arena_labels_unique():
    with pytest.raises(ValueError):
        ArenaSpec.model_validate({"name": "t", "roster": ["boulware", "boulware"]})
