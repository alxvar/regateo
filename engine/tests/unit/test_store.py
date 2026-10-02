from regateo.core import ActionKind, EndReason, Role
from regateo.core.agent import AgentRef
from regateo.llm.types import LLMCallRecord, Usage
from regateo.referee import DealEvent, score
from regateo.storage import Store
from tests.conftest import msg


async def test_round_trip(tmp_path, scenario):
    store = await Store.open(tmp_path / "t.db")
    run_id = await store.create_run("gym", "o1-vs-o2", {"pairs": 100})
    seller, buyer = AgentRef(name="o1", config={"model": "qwen-local"}), AgentRef(name="o2")
    mid = await store.start_match(scenario=scenario, seller=seller, buyer=buyer, protocol="freetext",
                                  run_id=run_id, seed=2**62, meta={"pair": 3})
    m0 = msg(0, Role.SELLER, "$170", ActionKind.OFFER, 170)
    m0.move.meta["rationale"] = "anchor high"
    await store.append_message(mid, m0)
    await store.append_message(mid, msg(1, Role.BUYER, "Deal, $170."))
    await store.record_llm_call(LLMCallRecord(profile="fake", provider="fake", model="fake",
                                              tags={"match": mid, "stage": "writer"},
                                              usage=Usage(input_tokens=10), cost_usd=0.01))
    outcome = score(scenario, DealEvent(price=140, accepted_by=Role.BUYER, idx=1, detector="t"),
                    EndReason.DEAL, messages=2)
    await store.finish_match(mid, outcome, cost_usd=0.01)
    await store.finish_run(run_id)

    [run] = await store.list_runs(kind="gym")
    assert run.status == "done" and run.config == {"pairs": 100}
    [row] = await store.list_matches(run_id)
    assert row.outcome == outcome and row.seller.key == seller.key and row.meta == {"pair": 3}
    assert row.scenario == scenario and row.seed == 2**62
    messages = await store.match_messages(mid)
    assert [m.text for m in messages] == ["$170", "Deal, $170."]
    assert messages[0].move.meta == {"rationale": "anchor high"}
    [call] = await store.match_llm_calls(mid)
    assert call.usage.input_tokens == 10 and call.tags["stage"] == "writer"
    await store.close()

    reopened = await Store.open(tmp_path / "t.db")                 # schema already there
    assert (await reopened.get_match(mid)).status == "done"
    await reopened.close()


async def test_thinking_traces(tmp_path, scenario):
    import sqlite3
    path = tmp_path / "t.db"
    store = await Store.open(path)
    run_id = await store.create_run("gym", "g", {})
    mid = await store.start_match(scenario=scenario, seller=AgentRef(name="a"), buyer=AgentRef(name="b"),
                                  protocol="freetext", run_id=run_id, seed=1, meta={})
    tags = {"match": mid, "agent": "a", "stage": "strategist"}
    await store.record_llm_call(LLMCallRecord(profile="p", provider="fake", model="m", tags=tags,
                                              reasoning="They opened low, so..."))
    await store.record_llm_call(LLMCallRecord(profile="p", provider="fake", model="m", tags=tags,
                                              error="LLMBadOutput: truncated", reasoning="Wait, maybe..."))
    await store.record_llm_call(LLMCallRecord(profile="p", provider="fake", model="m", tags=tags))
    [first, failed] = await store.run_reasoning(run_id)
    assert first["reasoning"] == "They opened low, so..." and first["tags"]["stage"] == "strategist"
    assert failed["error"] and failed["reasoning"] == "Wait, maybe..."
    assert [c.reasoning for c in await store.match_llm_calls(mid)] == ["They opened low, so...", "Wait, maybe...", ""]
    await store.reset_match(mid)
    assert await store.run_reasoning(run_id) == []
    await store.close()
    # A database made before the table existed gains it on open, without a schema version change.
    old = tmp_path / "old.db"
    await (await Store.open(old)).close()
    c = sqlite3.connect(old)
    c.execute("DROP TABLE llm_reasoning")
    c.commit()
    c.close()
    await (await Store.open(old)).close()
    c = sqlite3.connect(old)
    assert c.execute("SELECT name FROM sqlite_master WHERE name = 'llm_reasoning'").fetchone()
    assert c.execute("PRAGMA user_version").fetchone()[0] == 2


async def test_delete_run(tmp_path, scenario):
    import pytest
    store = await Store.open(tmp_path / "t.db")
    runs = []
    for name in ("stale", "kept"):
        run_id = await store.create_run("gym", name, {})
        mid = await store.start_match(scenario=scenario, seller=AgentRef(name="a"), buyer=AgentRef(name="b"),
                                      protocol="freetext", run_id=run_id, seed=1, meta={})
        await store.append_message(mid, msg(0, Role.SELLER, "$170", ActionKind.OFFER, 170))
        await store.record_llm_call(LLMCallRecord(profile="p", provider="fake", model="m", tags={"match": mid},
                                                  reasoning="hmm"))
        runs.append((run_id, mid))
    (stale, stale_match), (kept, kept_match) = runs
    assert await store.delete_run(stale) == 1
    assert await store.get_run(stale) is None and await store.get_match(stale_match) is None
    assert await store.match_messages(stale_match) == [] and await store.match_llm_calls(stale_match) == []
    assert await store.run_reasoning(stale) == []
    assert len(await store.match_messages(kept_match)) == 1 and len(await store.run_reasoning(kept)) == 1
    with pytest.raises(KeyError):
        await store.delete_run(stale)
    await store.close()
