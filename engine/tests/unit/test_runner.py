import pytest

from regateo.agents import AgentSpec
from regateo.core import ScenarioSpec, sample_scenarios
from regateo.llm import registry
from regateo.llm.limits import LimitedClient
from regateo.llm.providers.fake import FakeProvider
from regateo.opponents.llm import Decision
from regateo.runner import MatchJob, RunSettings, match_id, run_jobs
from regateo.storage import Store

SCEN = sample_scenarios(ScenarioSpec(per_cell=5), 1)


def jobs(seller="boulware", buyer="scripted:linear", n=5):
    return [MatchJob(key=str(i), scenario=SCEN[i], seller=AgentSpec.resolve(seller), buyer=AgentSpec.resolve(buyer),
                     seed=i, sim_clock=True) for i in range(n)]


async def test_runs_and_resumes(tmp_path):
    store = await Store.open(tmp_path / "db")
    rid = await store.create_run("gym", "t")
    s1 = await run_jobs(jobs(), store=store, run_id=rid)
    assert s1.done == 5 and s1.failed == 0
    # simulate a crash mid-match: one match left "running" with a stray message
    mid = match_id(rid, jobs()[0])
    await store.reset_match(mid)
    s2 = await run_jobs(jobs(), store=store, run_id=rid)
    assert s2.skipped == 4 and s2.done == 1
    assert len(await store.list_matches(rid)) == 5
    assert (await store.run_progress(rid))["total"] == 5


class Priced(FakeProvider):
    async def complete(self, req):
        r = await super().complete(req)
        return r.model_copy(update={"cost_usd": 0.05})


@pytest.fixture
def fake_profile(monkeypatch):
    fake = Priced(lambda req: Decision(action="offer", price=150, message="$150"), profile_name="fake")
    monkeypatch.setattr(registry, "_clients", {})
    monkeypatch.setattr(registry, "build_provider", lambda profile: fake)
    return fake


async def test_budget_stops_new_matches(tmp_path, fake_profile):
    store = await Store.open(tmp_path / "db")
    rid = await store.create_run("gym", "t")
    spec = {"kind": "o1", "model": "fake"}
    s = await run_jobs(jobs(spec, "scripted:hardliner", n=5), store=store, run_id=rid,
                       settings=RunSettings(concurrency=1, budget_usd=0.3))
    assert s.budget_exhausted and s.done + s.failed + s.skipped == 5 and s.skipped > 0
    calls = await store.match_llm_calls(match_id(rid, jobs()[0]))
    assert calls and calls[0].tags["role"] == "seller" and calls[0].tags["stage"] == "o1"


async def test_concurrency_cap(tmp_path, monkeypatch):
    fake = FakeProvider(lambda req: Decision(action="offer", price=150, message="$150"), delay_s=0.01)
    limited = LimitedClient(fake, 3)
    peak = 0
    orig = fake.complete

    async def tracking(req):
        nonlocal peak
        peak = max(peak, limited.in_flight)
        return await orig(req)

    fake.complete = tracking
    monkeypatch.setattr(registry, "get_client", lambda p: limited)
    monkeypatch.setattr("regateo.runner.runner.get_client", lambda p: limited)
    store = await Store.open(tmp_path / "db")
    rid = await store.create_run("gym", "t")
    await run_jobs(jobs({"kind": "o1", "model": "fake"}, n=5), store=store, run_id=rid,
                   settings=RunSettings(concurrency=5))
    assert peak == 3
