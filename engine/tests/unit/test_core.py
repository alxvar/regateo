from regateo.core import InfoMode, Role, ScenarioSpec, better_or_equal, other, sample_scenarios, sign
from regateo.core.agent import AgentRef
from regateo.core.ids import derive_seed


def test_u_space():
    assert sign(Role.SELLER) == 1 and sign(Role.BUYER) == -1
    assert other(Role.BUYER) is Role.SELLER
    assert better_or_equal(Role.SELLER, 120, 110)
    assert better_or_equal(Role.BUYER, 110, 120)


def test_surplus_share(scenario):
    assert scenario.zopa == 50
    assert scenario.surplus_share(Role.SELLER, 125) == 0.5
    assert scenario.surplus_share(Role.BUYER, 110) == 0.8
    assert scenario.surplus_share(Role.SELLER, None) == 0
    assert scenario.surplus_share(Role.SELLER, 90) < 0          # past our reservation


def test_view_hides_other_side(scenario):
    view = scenario.view_for(Role.BUYER)
    assert view.reservation == 150
    assert view.max_rounds is None                                # deadline hidden
    assert "100" not in view.model_dump_json()                    # seller's reservation never leaks


def test_sampling_is_deterministic_and_covers_grid():
    spec = ScenarioSpec(info_modes=[InfoMode.PRIVATE, InfoMode.FULL], max_rounds=[4, 8], per_cell=3)
    a, b = sample_scenarios(spec, 7), sample_scenarios(spec, 7)
    assert a == b and len(a) == 12
    assert len({s.id for s in a}) == 12
    full = [s for s in a if s.info_mode is InfoMode.FULL][0]
    assert full.seller_hint == (full.buyer_reservation, full.buyer_reservation)
    assert all(s.zopa > 0 for s in a)


def test_seeds_and_agent_keys():
    assert derive_seed(1, "a") == derive_seed(1, "a") != derive_seed(1, "b")
    assert derive_seed(1, "a") < 2**63
    assert AgentRef(name="o2", config={"b": 1, "a": 2}).key == AgentRef(name="o2", config={"a": 2, "b": 1}).key
