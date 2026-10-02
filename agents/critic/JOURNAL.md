# critic: journal

The record of what was tried on this architecture, version by version: the hypothesis, what changed, the run, and what it showed. Every session that changes this architecture reads it first and adds an entry when it's done. Newest last.

## v1

**2026-10-01. First version of docs/02 O6: a drafter decides, a critic reviews the draft before it is sent.**

- **Hypothesis:** a second call catches soft failures a numeric check can't see: hints at our limit or urgency, conceding too fast, obeying planted instructions, inconsistency, commitments we didn't mean. docs/02 notes it can make the agent stiff.
- **Shape:** the drafter (own prompt, one structured call) decides. Code vetoes the hard limits and agreement words first (one retry, then restate our last offer). Then the critic reviews the draft against the conversation (both quoted with `> `) and returns problems, five flags and a verdict. In `revise` mode a flagged draft is rewritten once with the review. If the revision fails its checks, the reviewed draft is sent. In `log` mode the draft is always sent. A failed critic call sends the draft.
- **Configs:** `revise` (2 calls per turn, 3 when revising), `log` (2; docs/02's key experiment: count catches against false alarms in the transcripts), `off` (no critic, the ablation; 1 call).
- **Logged:** `meta.critique`, `meta.flags`, and with a revision `meta.revised` and `meta.draft`.
- **Fixes after the first live matches** (shared code in `lib/common.py`, the same in tools, ranged, strategist and critic):
  - Reading their offer: the amount worst for us in their message picked up competitor quotes ("the other vendor's $72 … meet me at $90" read as $72). Facts now use the last amount of their own in the message. The limit check still reads defensively, except that a message that only restates our price ("Fine, $91") closes at that price. Before the fix, a valid acceptance of $91 was vetoed.
  - A decision that fails its checks twice keeps its own price within the limit, with a plain message ("I can do $150."), instead of restating the opening. The retry now shows the rejected draft.
- **Seen in the smoke matches, not fixed:** in 3 of 4 first matches the agent offered less than the other side had already offered (seller offering $95 against a $130 bid, $108 against $138.78), and once a critic revision held at $125 against $138.78. A veto on offers worse for us than their standing offer would catch it, but that is code deciding when to accept (docs/06 §3.3), so it is left for the user to decide.
- **Run:** dev run `run_01a0f82b4d9d29d2085c` (`engine/configs/gym/archs-v1.yaml`, standard-v2, reference `single_call/v1/baseline`, halving and early stopping). Code uncommitted (recorded as 26bea00a+23ada9b3c971). **Stopped** by us after 539 of 1,632 matches (it would have taken 6–8 more hours, mostly the strategist's thinking); not resumed. Final numbers: `revise` −0.051 (p = 0.59, n = 24), cut by halving after the first rung. Deals 54% vs 75%: the critic makes it stiff, as docs/02 feared. Gates fail: scripted:hardliner −0.107, scripted:injector −0.158. No deals past the limit. Nothing significant, so no conclusion.

## v2

**2026-10-01. Round 01 session: close the deals v1 left on the table.** Three variants of `critic/v1/revise`, all in `v2` (a copy of v1 plus a facts line, new prompts and a `stalls` flag; shared `lib/` untouched). Checked with `regateo-agent check` (run as `python -m agent_sdk.cli check`, the venv script's interpreter path is broken) and `pytest agents/critic`.

- **Failure targeted:** 20 of the 48 logged matches ended without a deal (`round_limit`), all with a zone of agreement. In many the other side had come to or past our last price and we never closed: seller 20-1-s, they at $151 vs our $158 with our limit at $123.49; 21-0-s, they at $150 while we offered $140 (below their standing offer); 21-1-s, they at $167 vs our $168; 20-0-b, they at $145 vs our $125 with a limit of $151.58. We conceded in small steps and ran out of messages. Also, the "mentions" veto fired on almost every rejection that quoted their price (28 repaired or fallback messages; one match ended on "My offer stands at $68" at round 6). The critic made it worse: its only pressure was `concedes_too_fast`.
- **Shared change (all three):** a line of facts for the drafter and the critic ("N messages left" or "this is your last message", their latest offer, ours); no walk-away comparison, given L2. The drafter prompt paces concessions to the message budget, says never to offer worse than their standing offer, asks for a closing move on the last message, and tells it to refer to their number as "your number" rather than write it (fewer vetoes). The critic has a `stalls` flag and is told not to flag a concession as too fast when they moved and messages are running out. No code chooses a price or an acceptance.
- **`close`** (critic revises): hypothesis: deal rate goes from 54% toward the reference's 75% and share rises above v1's 0.323. Wrong if the deal rate stays below 65% or the gates (hardliner, injector) still drop by more than 0.10.
- **`close_solo`** (same prompts and facts, no critic): hypothesis: the stiffness came from the critic's extra call, so this one closes at least as well as `close` with a third of the calls. Wrong if `close` beats it by 0.03 or more in share, or if it leaks the limit or follows planted instructions more (it gets the injector gates).
- **`close_nofacts`** (prompts and critic, `facts: false`): hypothesis: the facts line is what matters, so this one does worse than `close`. Wrong if it matches `close`: then the prompt text carries the effect and the facts line is not needed.
- **Not done:** the veto on quoted prices (L13) and the "offer worse than their standing offer" veto stay as they were; the second would be code deciding when to accept. No live run in this session, only the unit tests with fake models.

**Fixed by hand after collect, before the round's run:** v2's facts read our own offers with `lib.common.our_offers`, which looks only at the move's action and price. On free text the platform drops both from our own messages (what we meant is in `meta["intent"]`), so the facts said "your offers so far: none" every turn. v2 now reads them with its own `offers.py` (intent first, then the logged decision), tested in `tests/test_offers.py`. The same bug is in v1 (and in every version's `safe_move`, which therefore restates the opening price instead of our last offer: the "My offer stands at $68" seen in the data); v1 and `lib/` stay as they are.

**Round round-01** (run_01a0f9180ca60d701354), Δshare against the reference `single_call-v1-baseline` on standard-v2:

- `critic/v1/revise`: -0.051 [-0.235, +0.127]  p=0.5941 (not significant, n=24); A ahead in 38% of pairs, B in 46%, cut after 48 pairs
- `critic/v2/close`: -0.017 [-0.154, +0.115]  p=0.8116 (not significant, n=48); A ahead in 46% of pairs, B in 46%, cut after 96 pairs
- `critic/v2/close_nofacts`: +0.072 [-0.092, +0.243]  p=0.4192 (not significant, n=24); A ahead in 54% of pairs, B in 46%, cut after 48 pairs
- `critic/v2/close_solo`: -0.014 [-0.069, +0.041]  p=0.6157 (not significant, n=240); A ahead in 42% of pairs, B in 45% **(next parent)**
