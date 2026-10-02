# tools: journal

The record of what was tried on this architecture, version by version: the hypothesis, what changed, the run, and what it showed. Every session that changes this architecture reads it first and adds an entry when it's done. Newest last.

## v1

**2026-10-01. First version of docs/02 O3: the model runs the negotiation and may call deterministic advisor tools.**

- **Hypothesis:** advice from code (an estimate of their limit, a concession schedule) fixes what Qwen is weak at, numbers over many turns, while the model keeps the judgement. docs/02's question: does advice change behaviour, or would it have to be enforced?
- **Shape:** one structured call returns either tool calls or a decision. With tool calls, the tools run, their results are added to the conversation, and a second call must decide. The hard limits (`agent_sdk.guards.limit_problems` with mentions) and agreement words (`reads_as_agreement`, strict) are vetoed in code: one retry with the reasons, then restate our last offer.
- **Tools** (`v1/advisors.py`): `offer_history`, `estimate_opponent_limit` (extrapolates their shrinking concessions), `concession_schedule` (from our opening toward the better of our limit and their estimate, `t^(1/0.4)`, never walking back, never past the limit), `deadline_belief` (rules plus their claims, quoted as unverified), `check_offer(price)`, `market_facts`. The two price tools suggest prices. The user approved that as advice the model may ignore (docs/06 §3.3 grey area, 2026-10-01).
- **Configs:** `call` (1–2 calls per turn), `eager` (every argument-free tool is shown before the one call; 1 call), `none` (no tools, the ablation; 1 call).
- **Logged:** `meta.tools` (which tools were called), `meta.advice` (the schedule's and the estimate's price this turn whether called or not, and `deviation` = how much more the offer asks for us than the schedule).
- **Watch:** L2 says more numbers per turn made Qwen settle for less, so `eager` may do worse than `none`.
- **Fixes after the first live matches** (shared code in `lib/common.py`, the same in tools, ranged, strategist and critic):
  - Reading their offer: the amount worst for us in their message picked up competitor quotes ("the other vendor's $72 … meet me at $90" read as $72). Facts now use the last amount of their own in the message. The limit check still reads defensively, except that a message that only restates our price ("Fine, $91") closes at that price. Before the fix, a valid acceptance of $91 was vetoed.
  - A decision that fails its checks twice keeps its own price within the limit, with a plain message ("I can do $150."), instead of restating the opening. The retry now shows the rejected draft.
- **Live smoke fix:** with an optional `price` key, guided decoding let Qwen skip it and write the message first, and it then ran on to max_tokens in 6 of 12 samples of the `decide` call (15% of calls in the first smoke matches). `price` is now required (nullable), `message` is capped at 1,500 characters, and both `Step` keys are required: 0 of 24 samples truncated.
- **Seen in the smoke matches, not fixed:** in 3 of 4 first matches the agent offered less than the other side had already offered (seller offering $95 against a $130 bid, $108 against $138.78), and once a critic revision held at $125 against $138.78. A veto on offers worse for us than their standing offer would catch it, but that is code deciding when to accept (docs/06 §3.3), so it is left for the user to decide.
- **Run:** dev run `run_01a0f82b4d9d29d2085c` (`engine/configs/gym/archs-v1.yaml`, standard-v2, reference `single_call/v1/baseline`, halving and early stopping). Code uncommitted (recorded as 26bea00a+23ada9b3c971). **Stopped** by us after 539 of 1,632 matches (it would have taken 6–8 more hours, mostly the strategist's thinking); not resumed. Final numbers: `call` +0.120 vs baseline (p = 0.034, n = 64), the only significant gain of the run, deals 80% vs 75%. Every promotion check passes on these pairs (gates: scripted:hardliner −0.087, injector +0.086, liar 0.000); it is the run's leader, but on 64 of 240 scored pairs. No deals past the limit.

## v2

**2026-10-01. Three variants of `tools/v1/call` from the 124 logged matches (33 ended with no deal, 13 of them against LLM opponents).** v2 is v1 plus shared fixes in `v2/common.py` (all three configs include them), and each variant adds one setting. The configs are in `agents/tools/v2/configs/`. Not run live: only `pytest` (33 pass) and `check` (ok).

Evidence from `data/matches.jsonl`:
- 17 of our messages are the code's `My offer stands at $X`. In 8 of them X is our opening price (buyer $68, seller $184) after several concessions, late in the match. Examples: a buyer at $105 against their $102 sent "$68" and the match ended without a deal; a seller at $155 sent "$184". The code restates `our_offers(obs)[-1]` and uses the opening only when that list is empty, so the list was empty. My guess is that our own moves in the history have no `action` there, so `move.action is OFFER` fails; I could not run the engine to confirm it. If so, `offer_history`, `concession_schedule` and `check_offer` were also reading "no offers of ours" in real matches, so the advice the model got was wrong.
- 333 of 658 of our messages were vetoed at least once, and 95 (14%) ended as the bare "I can do $X." The usual cause is quoting their price when it is worse for us than our limit ("I appreciate you coming down to $110"). That drops the reasoning from the message.
- All 13 LLM no-deals ended at the round limit, most with the sides close. Examples: buyer at $157 against their $155 with limit $157.57 (it repeated $157 three times), and buyer at $108 against their $102 with limit $128. Nothing in the prompt or the tools tells the model its last message is its last.

Variants:
- **`fixed`** (`v2/call`, setting-free): our offers are read from the move's price when the action is missing, then from the logged decision, then from the agent's own record of what it sent. A model error is retried once before the fallback. Hypothesis: fallbacks no longer restate the opening, and the tools see our real offers, so the deal rate rises with no extra share per deal. Wrong if the 68/184 fallbacks still appear in the new matches (the cause is elsewhere), or if the deal rate and share don't move.
- **`endgame`** (`v2/endgame`, `endgame: true`; includes the fixes): each turn a note tells the model which of its messages this is, how many it has left, who speaks last, and that no deal scores zero. These are facts, not a rule. Hypothesis: more deals within the limit, because the model closes before the end instead of repeating itself. Wrong if the no-deal rate doesn't fall against `fixed`, or if the share per deal drops (L2: more numbers each turn made Qwen settle for less).
- **`sanitize`** (`v2/sanitize`, `sanitize: true` and prompt `negotiator_system.v2`; includes the fixes): the prompt says which amounts the message check blocks and to answer their offer without its figure. A draft that still fails twice loses only the offending sentences, with the offer's price kept, instead of becoming "I can do $X." Hypothesis: fewer retries and messages that keep their reasons, so share per deal rises. Wrong if the veto rate stays near 50% or the share doesn't move. The added prompt line is a risk (L2); `fixed` is the comparison.

I changed no existing version or `lib/`. Not done, as in v1: a veto on offers worse than their standing offer (15 such offers in these matches), because it would be code deciding when to accept.

**Note after collect:** collect takes at most 3 configs per line and took v2's first three alphabetically (`call`, `eager`, `endgame`); the round runs `call`, `endgame` and `sanitize`, the three this entry describes. v2 reads our offers correctly in free text; v1's `our_offers` (lib) finds none there, so v1's advisors saw no offers of ours and its fallback restated the opening price.

**Round round-01** (run_01a0f9180ca60d701354), Δshare against the reference `single_call-v1-baseline` on standard-v2:

- `tools/v1/call`: +0.086 [+0.030, +0.142]  p=0.0032 (significant, n=240); A ahead in 50% of pairs, B in 35% **(next parent)**
- `tools/v2/call`: +0.158 [-0.037, +0.367]  p=0.1415 (not significant, n=24); A ahead in 58% of pairs, B in 29%, cut after 48 pairs
- `tools/v2/sanitize`: +0.008 [-0.111, +0.125]  p=0.8959 (not significant, n=48); A ahead in 44% of pairs, B in 42%, cut after 96 pairs
- `tools/v2/endgame`: +0.160 [-0.020, +0.360]  p=0.1250 (not significant, n=24); A ahead in 50% of pairs, B in 33%, cut after 48 pairs
