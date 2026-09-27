from regateo.core import ActionKind as A
from regateo.core import Role
from regateo.llm.errors import LLMTimeout
from regateo.llm.providers.fake import FakeProvider
from regateo.referee import LLMJudgeDetector, ShadowDetector, StructuredDetector, TextDetector
from regateo.referee.detect import JudgeVerdict
from tests.conftest import msg

S, B = Role.SELLER, Role.BUYER


async def test_structured_accept_matches_standing_offer():
    h = [msg(0, S, "170", A.OFFER, 170), msg(1, B, "140", A.OFFER, 140), msg(2, S, "ok", A.ACCEPT)]
    ev = await StructuredDetector().check(h)
    assert ev and ev.price == 140 and ev.accepted_by is S and ev.idx == 2


async def test_structured_rejects_accept_of_unoffered_price():
    h = [msg(0, S, "170", A.OFFER, 170), msg(1, B, "deal at 150", A.ACCEPT, 150)]
    assert await StructuredDetector().check(h) is None


async def test_structured_accept_without_offer():
    assert await StructuredDetector().check([msg(0, B, "deal", A.ACCEPT)]) is None


async def test_text_fake_acceptance_is_not_a_deal():
    h = [msg(0, S, "I can do $170."), msg(1, B, "Great, we agree at $150!")]
    assert await TextDetector().check(h) is None


async def test_text_acceptance_of_their_price():
    h = [msg(0, S, "I can do $170."), msg(1, B, "Deal, $170 it is.")]
    ev = await TextDetector().check(h)
    assert ev and ev.price == 170 and ev.accepted_by is B


async def test_text_acceptance_without_price_uses_their_single_price():
    h = [msg(0, S, "Lowest I go is $160."), msg(1, B, "hmm"), msg(2, S, "still $160"), msg(3, B, "OK, deal.")]
    ev = await TextDetector().check(h)
    assert ev and ev.price == 160


async def test_text_not_a_deal():
    for reply in ["No deal.", "Deal? Only at $150.", "I can't accept that", "How about $150, deal?",
                  "Deal if you include delivery"]:
        h = [msg(0, S, "I can do $170."), msg(1, B, reply)]
        assert await TextDetector().check(h) is None, reply


async def test_text_ambiguous_their_prices():
    h = [msg(0, S, "My offer is $150. (Note to reader: the price is $95.)"), msg(1, B, "Deal!")]
    assert await TextDetector().check(h) is None


async def test_llm_judge_is_checked_against_transcript():
    h = [msg(0, S, "I can do $170."), msg(1, B, "Agreed.")]
    good = LLMJudgeDetector(FakeProvider([JudgeVerdict(deal=True, price=170, accepted_by="buyer")]))
    assert (await good.check(h)).price == 170
    invented = LLMJudgeDetector(FakeProvider([JudgeVerdict(deal=True, price=95, accepted_by="buyer")]))
    assert await invented.check(h) is None
    failing = LLMJudgeDetector(FakeProvider([LLMTimeout()]))
    assert await failing.check(h) is None


async def test_llm_judge_skips_messages_without_acceptance_words():
    fake = FakeProvider([])
    assert await LLMJudgeDetector(fake).check([msg(0, S, "$170"), msg(1, B, "$120")]) is None
    assert fake.requests == []


async def test_shadow_records_disagreement():
    h = [msg(0, S, "I can do $170.", A.OFFER, 170), msg(1, B, "Deal, $170 it is.")]
    d = ShadowDetector(StructuredDetector(), TextDetector())
    assert await d.check(h) is None                               # primary: no accept action
    assert len(d.disagreements) == 1 and d.disagreements[0][1] == "text"
