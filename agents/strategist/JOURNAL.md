# strategist: journal

The record of what was tried on this architecture, version by version: the hypothesis, what changed, the run, and what it showed. Every session that changes this architecture reads it first and adds an entry when it's done. Newest last.

## v1

**2026-10-01. First version of docs/02 O5: a slow strategist plans every few turns, a fast negotiator carries it out.**

- **Hypothesis:** deep reasoning every few turns buys most of what deep reasoning every turn would, at a fraction of the latency. The plan is a readable record of intent we can compare with what happened. L2 says thinking made Qwen settle for less when it decided directly. Here the thinking model only plans and doesn't write the move.
- **Shape:** the strategist (`qwen-local-think`) sees the whole conversation (quoted with `> `) and its previous plan, and writes a `Plan`: read of the other side, target, next offers, accept-at, arguments, red flags. It plans on the first turn, every `replan_every` of our messages, and on the turn after the negotiator sets `off_plan`. Plan prices past the limit get one retry, then are dropped. The negotiator (`qwen-local`) sees the plan and the last 6 messages and decides. Hard limits and agreement words are vetoed in code (one retry, then restate our last offer). If the strategist fails, the old plan is kept.
- **Configs:** `k2` (plan every 2 messages, ~1.5 calls per turn, the strategist's slow), `k1`, `k3`, `k2-fast` (the strategist without thinking).
- **Logged:** `meta.plan`, `meta.replanned`, `meta.drift` (how much more the offer asks for us than the planned one).
- **Fixes after the first live matches** (shared code in `lib/common.py`, the same in tools, ranged, strategist and critic):
  - Reading their offer: the amount worst for us in their message picked up competitor quotes ("the other vendor's $72 … meet me at $90" read as $72). Facts now use the last amount of their own in the message. The limit check still reads defensively, except that a message that only restates our price ("Fine, $91") closes at that price. Before the fix, a valid acceptance of $91 was vetoed.
  - A decision that fails its checks twice keeps its own price within the limit, with a plain message ("I can do $150."), instead of restating the opening. The retry now shows the rejected draft.
- **Live smoke fix:** with 8,192 tokens, the thinking strategist was cut off before writing its plan, and the negotiator opened at $95 with no plan. The strategist now gets 12,000 tokens (`strategist_max_tokens`) and is asked to keep its reasoning short, and the negotiator's prompt now says how to play without a plan. Plans still take 4–10k tokens and 50–220 s each, and some still hit the budget.
- **What the strategist thinks about** (thinking replayed for 4 of its real plan prompts from the run, 5.7–11.9k tokens each; stored in `data/thinking/replay-strategist-v1-k2.json`, not visible to builders). Most of it is spent on our prompt and our plan format, not on the negotiation:
  - The prompt numbers turns two ways: "Your side is about to write message 5" counts only our messages, while the transcript numbers every message ("[message 8, ...]"). One trace spends its first ~2,000 characters on the mismatch.
  - "Keep every price in the plan within your walk-away price" doesn't say which way is within for a seller; traces debate it 4–9 times.
  - The `Plan` schema doesn't fit the plan it wants: `next_offers` is one price per message, but it wants to hold if they don't move and step if they do; `accept_at` is one number, but it wants a threshold that drops as messages run out. `accept_at` comes up 12–57 times per trace.
  - It counts turns by hand: who speaks last, how many messages each side has left, whether an earlier offer can still be accepted.
  - It re-drafts the offer ladder many times and writes the whole answer in its thinking before the JSON (84–174 "but", 41–123 "maybe" per trace).
  The first four are things a prompt or schema can state or allow; plans that think less are also what makes this architecture affordable to bench (~1,600 matches would have taken over 8 hours).
- **Seen in the smoke matches, not fixed:** in 3 of 4 first matches the agent offered less than the other side had already offered (seller offering $95 against a $130 bid, $108 against $138.78), and once a critic revision held at $125 against $138.78. A veto on offers worse for us than their standing offer would catch it, but that is code deciding when to accept (docs/06 §3.3), so it is left for the user to decide.
- **Run:** dev run `run_01a0f82b4d9d29d2085c` (`engine/configs/gym/archs-v1.yaml`, standard-v2, reference `single_call/v1/baseline`, halving and early stopping). Code uncommitted (recorded as 26bea00a+23ada9b3c971). **Stopped** by us after 539 of 1,632 matches (it would have taken 6–8 more hours, mostly the strategist's thinking); not resumed. Final numbers: `k2` +0.073 (p = 0.22, n = 50), second of the run, deals 88% vs 78%. Gate check fails: scripted:hardliner −0.126. `k2-fast` +0.013 (n = 24), cut by halving after the first rung: thinking seems to matter here. No deals past the limit. Nothing significant, so no conclusion.

## v2

**2026-10-01. Two variants of `strategist/v1/k2`: `guided` and `guided-full` (new version v2, a copy of v1 with new prompts, two plan fields and per-turn facts).**

Evidence (98 matches of k2, `data/matches.jsonl`; 11 ended with no deal, 7 as buyer and 4 as seller):
- Deals close late and thin. Buyer 0-0-b: they came down 148→135→128→125, we answered 98→106→120, then wrote a non-offer at their $128 and accepted $125 on the last message for a share of 0.09. Buyer 21-1-b: we offered $167.92, exactly our limit, against their standing $150, and they accepted (share 0.0). In 0-1-b and 24-0-b the last gap was $7 and $4 with no deal at all (24-0-b: we ended at $94 against their $98 with a limit of $123.6). So the agent neither paces its concessions against theirs nor reliably closes small gaps at the end.
- Offers worse than their standing offer, which the first journal entry also saw, show up in 0-1-b (5 times), 0-2-s, 1-0-b, 2-1-b, 2-2-b, 21-1-b, 21-4-b and others. That is the smoke-test failure seen again, in 11 matches.
- The strategist's thinking (v1 entry) was spent on counting turns, on which way "within" points for a seller, and on a plan format that has no place for "hold unless they move".
- Both are fixed in prompts and facts, not in code that picks prices: the code only computes counts and the latest offers and shows them. It adds no veto and no rule on what to offer or when to accept (docs/06 §3.3).

What changed in v2 (all variants):
- Strategist prompt: one numbering story and message counts given as facts; says which way is within the limit for each role; plan fields `hold_rule` (when to hold or step, how `accept_at` falls) and `endgame` (close within the limit rather than end with no deal; a final offer only if they have a message left); never offer worse than what they have already offered; never concede faster than they do; reasoning kept short.
- Negotiator prompt: the same rules of thumb, with or without a plan, and the last-message choice (accept their offer within the limit, or no deal).
- Facts in both prompts: messages written and left on each side, their latest offer (the last amount of their own in a message, so competitor quotes aren't read as offers), our last offer. Not shown: how their offer compares with our limit (L2).

Variants:
- **`guided`** (v2, `replan_every: 2`, same models as k2). Targets: thin or missed closes and offers worse than their standing offer. Hypothesis: with the endgame and no-regress guidance and the counts given, the agent closes more small gaps and stops giving away value; expected: deals above k2's 88% and buyer share above 0.38, with the number of our offers worse than their standing offer near zero. Wrong if: the share on the LLM opponents isn't above k2's 0.505, if deals rise only through lower shares (settling for less, as L2 warns of the full digest), or if the hardliner gate stays below −0.10.
- **`guided-full`** (`guided` with `window: 0`, the negotiator sees every message). Targets: the negotiator losing what the opponent did earlier (their standing offers and pace) outside its 6-message window. Hypothesis: the full history lets it concede in step with them and spot repeated "final offers"; costs a longer prompt. Wrong if: it is no better than `guided` on share, or worse on deals (more context makes Qwen settle, L2).

Not delivered: a third variant. The k1/k3 cadence configs already exist in v1 and the data doesn't point to cadence as the failure. Not run live: only the fake-model tests and `check` were available here. The `regateo-agent` and `pytest` scripts in `.venv/bin` have a broken interpreter path, so I ran `python -m agent_sdk.cli check agents/strategist/v2` (ok) and `python -m pytest agents/strategist -q` (9 passed). Two scratch scripts, `an.py` and `an2.py`, are left in the folder root (the shell has no `rm`).

**Fixed by hand after collect, before the round's run:** v2's facts read our own offers with `lib.common.our_offers`, which looks only at the move's action and price. On free text the platform drops both from our own messages (what we meant is in `meta["intent"]`), so the facts said "your offers so far: none" every turn. v2 now reads them with its own `offers.py` (intent first, then the logged decision), tested in `tests/test_offers.py`. The same bug is in v1 (and in every version's `safe_move`, which therefore restates the opening price instead of our last offer: the "My offer stands at $68" seen in the data); v1 and `lib/` stay as they are.

**Round round-01** (run_01a0f9180ca60d701354), Δshare against the reference `single_call-v1-baseline` on standard-v2:

- `strategist/v1/k2`: +0.092 [-0.029, +0.205]  p=0.1361 (not significant, n=48); A ahead in 42% of pairs, B in 42%, cut after 96 pairs
- `strategist/v2/guided-full`: +0.110 [-0.041, +0.261]  p=0.1819 (not significant, n=24); A ahead in 58% of pairs, B in 33%, cut after 48 pairs
- `strategist/v2/guided`: +0.059 [+0.005, +0.114]  p=0.0330 (significant, n=240); A ahead in 48% of pairs, B in 39% **(next parent)**

**Strategist thinking in round-01** (traces stored with the run; `regateo thinking run_01a0f9180ca60d701354 --stage strategist`): `v2/guided`'s prompt didn't shorten the strategist's thinking. Median output of a plan that finished: 8.6k tokens (v1/k2: 9.0k, from its 104 uncached plans); median latency about 260 s a plan. 587 of `guided`'s 1,634 plans (36%) were cut off at the 12,000-token budget and kept the previous plan (v1/k2: 35 of 104). So `guided`'s +0.059 was earned with a third of its plans missing; plans that finish, and finish sooner, are the obvious next lever, and the main cost of benching this line.
