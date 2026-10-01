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
