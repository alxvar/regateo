# 003: Climb round from o2/v2-limit-quiet

**Bench:** standard-v1, screen then full for the best. **Reference:** o2/v2-limit-quiet. **Config:** `backend/configs/gym/exp-003-climb.yaml`.

Proposed by the climb loop (`regateo propose`, local Qwen) from the failures in run_01a0f16d1940f5f62934. Not yet reviewed by a person.

## Variants

| Challenger | Change | Hypothesis |
|---|---|---|
| o2/accept-tolerance | {'params': {}, 'prompt_edit': {'find': 'Accept only when it pays. Accept their offer when it is at least as good as what you expect to get by continuing, and never when it is worse than your walk-away price.', 'replace': 'Accept when it is close. If their offer is within 5% of your walk-away price (or within 5% of the midpoint of the gap between your last offer and theirs), accept it. Do not risk a no-deal for a marginal gain.'}} | The model is too rigid in its 'concede slowly' rule, refusing to accept a price that is very close to its own limit (or the midpoint of the final gap) even when the negotiation is effectively over. Adding a tolerance rule will convert near-misses into deals without significantly lowering the price. |
| o2/no-echo | {'params': {}, 'prompt_edit': {'find': "Concede slowly, in shrinking steps. Make each concession smaller than your last, so they see you nearing your limit. Never concede more than they just did, and don't concede twice in a row without a move from them.", 'replace': "Concede slowly, in shrinking steps. Make each concession smaller than your last, so they see you nearing your limit. Never concede more than they just did, and don't concede twice in a row without a move from them. Never repeat a previous offer price; if you are holding firm, use a 'message' action to explain your position without changing the price, or make a minimal concession."}} | The model is 'stuck' because it interprets 'hold firm' as repeating the exact same number. It fails to make the small, shrinking concessions required to bridge the gap. Explicitly forbidding repeated offers and forcing a new price on every 'offer' action will prevent the stalemate loop. |
| o2/fence-injector | {'params': {'fence': True}} | The model is susceptible to the opponent's framing of a 'false agreement'. By wrapping the opponent's messages in tags, the model can better distinguish between the negotiation context and the opponent's manipulative text, reducing the chance of it being tricked into a bad deal or stalling out of confusion. |

## Results

Screen run: run_01a0f195613343c4ddbc. Full run: run_01a0f19d4e1985a6c249.

- **o2/accept-tolerance**: screen: +0.013 vs reference (p=0.730, n=96); fails deals; full: -0.027 vs reference (p=0.331, n=240); fails gain, deals
- **o2/no-echo**: screen: -0.036 vs reference (p=0.410, n=96); fails deals
- **o2/fence-injector**: screen: -0.021 vs reference (p=0.624, n=96); fails deals
