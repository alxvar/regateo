"""Running many agent variants head to head: identity, replay across runs, benches, challengers."""
import pytest

from regateo.agents import AgentSpec
from regateo.agents.baselines.o1 import Decision
from regateo.core import ScenarioSpec, frozen, sample_scenarios
from regateo.gym import GymSpec, build_gym_report, run_gym
from regateo.llm import registry
from regateo.llm.cache import CachedClient, CacheMode
from regateo.llm.providers.fake import FakeProvider
from regateo.llm.types import LLMRequest
from regateo.runner import MatchJob, RunSettings, run_jobs
from regateo.storage import Store

SOFT = {"kind": "boulware", "name": "soft", "params": {"boulware": 1.5}}


def test_frozen_files_unchanged():
    assert frozen.changed() == [], (
        "frozen files changed (configs/frozen.json). They have benchmark results: add a new version "
        "(e.g. negotiator_system.v2.md) instead. If the edit really changes nothing, re-run `regateo freeze`.")


async def test_profile_settings_are_part_of_the_cache_key(tmp_path):
    inner = FakeProvider(lambda req: "ok")
    await CachedClient(inner, tmp_path / "c.db", profile_key="p1").complete(LLMRequest.of("x"))
    await CachedClient(inner, tmp_path / "c.db", profile_key="p1").complete(LLMRequest.of("x"))
    assert len(inner.requests) == 1
    await CachedClient(inner, tmp_path / "c.db", profile_key="p2").complete(LLMRequest.of("x"))
    assert len(inner.requests) == 2                       # e.g. thinking switched on: not a replay


def test_identity_covers_prompts_and_profile():
    base = AgentSpec(kind="o1", model="qwen-local")
    cfg = base.ref().config
    assert set(cfg["prompts"]) == {"negotiator_system.v1"} and cfg["profile"]
    assert AgentSpec(kind="persona:tough", model="qwen-local").ref().config["prompts"].keys() == {
        "negotiator_system.v1", "persona_tough"}
    other_prompt = AgentSpec(kind="o1", model="qwen-local", params={"prompt": "persona_naive.v1"})
    assert other_prompt.ref().key != base.ref().key
    assert AgentSpec(kind="o1", model="claude-opus-5").ref().config["profile"] != cfg["profile"]


def test_extends(tmp_path, monkeypatch):
    agents = tmp_path / "agents"
    (agents / "o1").mkdir(parents=True)
    (agents / "base.yaml").write_text("kind: o1\nmodel: qwen-local\nname: base\nparams: {fence: true, effort: low}\n")
    (agents / "o1" / "hot.yaml").write_text("extends: base\nparams: {effort: high}\n")
    (agents / "loop.yaml").write_text("extends: loop\n")
    monkeypatch.setenv("REGATEO_CONFIGS", str(tmp_path))
    spec = AgentSpec.resolve("o1/hot")
    assert spec.kind == "o1" and spec.label == "o1-hot" and spec.params == {"fence": True, "effort": "high"}
    inline = AgentSpec.resolve({"extends": "base", "name": "cold", "params": {"effort": "min"}})
    assert inline.label == "cold" and inline.params == {"fence": True, "effort": "min"}
    with pytest.raises(ValueError, match="loop"):
        AgentSpec.resolve("loop")


def test_replay_key_is_what_the_match_is():
    s = sample_scenarios(ScenarioSpec(per_cell=1), 1)[0]
    seller = AgentSpec.resolve("boulware")
    job = MatchJob(key="x", scenario=s, seller=seller, buyer=AgentSpec(kind="scripted:liar"))
    renamed = job.model_copy(update={"key": "y", "seller": seller.model_copy(update={"name": "champion"}),
                                     "meta": {"pair": "7"}})
    assert renamed.replay_key() == job.replay_key()
    assert job.model_copy(update={"seed": 1}).replay_key() != job.replay_key()


async def test_a_new_run_replays_the_same_matches(tmp_path, monkeypatch):
    fake = FakeProvider(lambda req: Decision(action="offer", price=150, message="$150"), profile_name="fake")
    monkeypatch.setattr(registry, "_clients", {})
    monkeypatch.setattr(registry, "build_provider", lambda profile: fake)
    monkeypatch.setenv("REGATEO_DATA", str(tmp_path))
    scen = sample_scenarios(ScenarioSpec(per_cell=2), 1)
    jobs = [MatchJob(key=str(i), scenario=s, seller=AgentSpec(kind="o1", model="fake"),
                     buyer=AgentSpec(kind="scripted:hardliner"), seed=i, sim_clock=True) for i, s in enumerate(scen)]
    store = await Store.open(tmp_path / "db")
    settings = RunSettings(cache=CacheMode.READWRITE)
    await run_jobs(jobs, store=store, run_id=await store.create_run("gym", "one"), settings=settings)
    calls = len(fake.requests)
    assert calls > 0
    rid = await store.create_run("gym", "two")
    await run_jobs(jobs, store=store, run_id=rid, settings=settings)
    assert len(fake.requests) == calls                    # a different run, same matches: all replayed
    assert "commit" in (await store.get_run(rid)).config["code"]


def _bench(tmp_path, monkeypatch):
    (tmp_path / "benches").mkdir()
    (tmp_path / "benches" / "b1.yaml").write_text(
        "opponents: [scripted:hardliner, scripted:pushover]\n"
        "scenarios: {per_cell: 5, max_rounds: [4, 8]}\ntiers: {screen: 2}\nsim_clock: true\nseed: 3\n")
    monkeypatch.setenv("REGATEO_CONFIGS", str(tmp_path))


def test_bench_fixes_its_fields_and_tiers_are_subsets(tmp_path, monkeypatch):
    _bench(tmp_path, monkeypatch)
    spec = {"name": "t", "bench": "b1", "reference": "boulware", "challengers": [SOFT]}
    full = GymSpec.model_validate(spec)
    assert full.mode == "benchmark" and full.b.label == "boulware" and full.a.label == "soft"
    screen = GymSpec.model_validate({**spec, "tier": "screen"})
    full_jobs = {j.key: j for j in full.jobs()}
    screen_jobs = screen.jobs()
    assert len(screen_jobs) == len(full_jobs) * 2 // 5
    assert all(full_jobs[j.key].replay_key() == j.replay_key() for j in screen_jobs)
    with pytest.raises(ValueError, match="fixes"):
        GymSpec.model_validate({**spec, "seed": 4})
    with pytest.raises(ValueError, match="tier"):
        GymSpec.model_validate({**spec, "tier": "huge"}).jobs()


async def test_several_challengers_against_one_reference(tmp_path, monkeypatch):
    _bench(tmp_path, monkeypatch)
    spec = GymSpec.model_validate({"name": "t", "bench": "b1", "tier": "screen", "reference": "boulware",
                                   "challengers": [SOFT, {"kind": "boulware", "name": "hard",
                                                          "params": {"boulware": 8}}]})
    store = await Store.open(tmp_path / "db")
    run_id, summary = await run_gym(spec, store)
    pairs = 2 * 2 * 2 * 2                                  # cells x scenarios x opponents x roles
    assert summary.done == summary.total == pairs * 3
    r = await build_gym_report(store, run_id)
    assert [(c.subject, c.side.label, c.diff.n) for c in r.challengers] == [("a", "soft", pairs), ("a2", "hard", pairs)]
    assert r.challengers[0].diff.mean_diff == pytest.approx(r.diff.mean_diff)
    assert r.challengers[1].reference.label == "boulware"


def test_jobs_interleave_cells():
    jobs = GymSpec.model_validate({"name": "t", "reference": "boulware", "challengers": [SOFT],
                                   "opponents": ["scripted:hardliner"],
                                   "scenarios": {"per_cell": 3, "max_rounds": [4, 8]}}).jobs()
    cells = [j.meta["cell"] for j in jobs[::4]]            # 4 jobs per scenario: 2 roles x 2 subjects
    assert cells[:2] != [cells[0]] * 2 and len(set(cells[:2])) == 2


def test_early_stopper_drops_only_clear_losers():
    from regateo.gym.early import EarlyStop, EarlyStopper
    stop = EarlyStopper(EarlyStop(min_pairs=10, every=5), ["a", "a2"])
    for i in range(10):
        stop.add(str(i), "a", 0.1 + 0.01 * (i % 3))          # well behind the reference
        stop.add(str(i), "a2", 0.5 + 0.05 * (-1) ** i)       # level with it
        stop.add(str(i), "b", 0.5)
    assert stop.stopped == {"a": 10}
    job = MatchJob(key="k", scenario=sample_scenarios(ScenarioSpec(per_cell=1), 1)[0],
                   seller=AgentSpec(kind="boulware"), buyer=AgentSpec(kind="scripted:liar"))
    assert stop.skip(job.model_copy(update={"meta": {"subject": "a"}}))
    assert not stop.skip(job.model_copy(update={"meta": {"subject": "a2"}}))
    assert not stop.skip(job.model_copy(update={"meta": {"subject": "b"}}))
    stop.stopped["a2"] = 12
    assert stop.skip(job.model_copy(update={"meta": {"subject": "b"}}))    # nobody left to compare with


async def test_early_stop_in_a_gym(tmp_path, monkeypatch):
    _bench(tmp_path, monkeypatch)
    spec = GymSpec.model_validate({"name": "t", "bench": "b1", "reference": "boulware",
                                   "challengers": [{"kind": "scripted:pushover", "name": "pushover"}, SOFT],
                                   "early_stop": {"min_pairs": 8, "every": 4}, "settings": {"concurrency": 1}})
    store = await Store.open(tmp_path / "db")
    run_id, summary = await run_gym(spec, store)
    assert summary.skipped > 0 and summary.done < summary.total
    r = await build_gym_report(store, run_id)
    pushover = next(c for c in r.challengers if c.side.label == "pushover")
    assert pushover.stopped_at == 8 and pushover.diff.n == 8
    assert pushover.checks[0].name == "gain" and pushover.checks[0].status == "fail"


def test_promotion_checks():
    from regateo.gym.report import Breakdown, ChallengerStats, SideStats, promotion_checks
    from regateo.stats import mean_ci, paired_test, wilson

    def side(deals, past=0):
        return SideStats(label="x", matches=100, mean_share=mean_ci([0.3] * 100), deal_rate=wilson(deals, 100),
                         past_reservation=past, errors=0)

    diffs = [0.2, 0.1, 0.15, 0.05] * 25
    c = ChallengerStats(subject="a", side=side(80), reference=side(81), diff=paired_test(diffs),
                        by_opponent=[Breakdown(key="liar", a=mean_ci([0.1]), b=mean_ci([0.3]),
                                               diff=paired_test([-0.2] * 3 + [-0.1]))])
    status = {k.name: k.status for k in promotion_checks(c, purpose="dev", tier=None)}
    assert status == {"gain": "pass", "limit": "pass", "deals": "pass", "opponents": "warn"}
    assert promotion_checks(c, purpose="dev", tier="screen")[0].status == "n/a"
    worse = c.model_copy(update={"side": side(70, past=2), "diff": paired_test([-0.01, 0.02] * 20)})
    status = {k.name: k.status for k in promotion_checks(worse, purpose="holdout", tier=None)}
    assert status["gain"] == "pass" and status["limit"] == "fail" and status["deals"] == "fail"
