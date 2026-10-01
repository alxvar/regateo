# 05: Learnings

Status: **living**. What we currently believe about negotiating agents and how to measure them, with the evidence for each belief and how far that evidence reaches. It is updated after every experiment, so we build on what we found instead of re-running it, and so beliefs that rest on weak evidence stay visible as weak. The climb loop's proposer reads this page as part of "already tried".

## How the record works

Three records, each with one job:

| Record | Job | Changes |
|---|---|---|
| [experiments/NNN-*.md](experiments/README.md) | One try: hypothesis, configs, run ids, numbers, what it says | Written once; afterwards only corrected |
| [Experiment log](experiments/README.md#log) | The journal: every try in order, one line each | One row per experiment |
| This page | What we believe now, across all tries | Updated after every experiment |

**After each experiment:**

1. End its write-up with a `## Learnings` section that lists every entry it adds or changes here: `L7 strengthened`, `L12 new`, `L3 refuted`.
2. Make those changes here. Add a new entry, or edit the existing one: its status, evidence, scope, and a `Changed:` line with the date and the experiment that moved it.
3. Never delete an entry. A belief that turned out wrong stays, marked **refuted** and saying what refuted it, so nobody rediscovers it.

**Who sees what.** A session building an agent sees only the public view of this page (`regateo learnings --public`; sections marked `<!-- visibility: internal -->` and internal entries are left out) and its own architecture's `JOURNAL.md` ([06 §5](06-agent-contract.md#5-what-a-builder-may-look-at)). What one architecture learns reaches another only when a person writes it here as a public entry: check that it follows from results, not from having read the code.

**Journals.** Each architecture keeps `agents/<architecture>/JOURNAL.md`: what was tried on it, version by version, with the run and the result. The session that changes the architecture writes it. A lesson from a journal that holds beyond that architecture comes here.

**Each entry has:**

- **Status:**
  - **holds:** a significant result, or the same effect in more than one experiment.
  - **suggestive:** one result that is not significant, or reasoning that hasn't been tested.
  - **refuted:** later evidence went against it.
  - **policy:** a decision we hold to without proof, with the reason why.
- **Evidence:** experiments and run ids, with the numbers that matter.
- **Scope:** which model, opponents, benches and rules the evidence covers. This is how we judge robustness: a belief tested only against Qwen opponents on 6-round matches says nothing yet about an Opus-class opponent or a 20-round match.
- **So:** what it means for the next design or experiment.
- **Revisit if:** what would make it worth testing again. Optional.
- **Visibility:**
  - **public:** it can be derived from match results alone and says nothing about how any agent, opponent or the referee works inside. Every agent builder sees it.
  - **internal:** it describes an agent's design, an opponent, a bench or the referee. People see it; builder sessions don't.

Sources older than the experiment log: idea-1 (first prototype, offline arena: [learnings/idea-1.md](learnings/idea-1.md)) and the experiments before the reset of 2026-09-30, which are in git history before this page and in the run archive `data/archive-2026-09-30/`. They are cited as "idea-1" and "pre-reset".

## The current reference and why

<!-- visibility: internal -->

`single_call/v1/baseline` (`agents/single_call/v1/configs/baseline.yaml`) is O1's single model call per turn, with strategy prompt `negotiator_system.v2` (L1), plus two of O2's code vetoes: `checks: limit+mentions` (L7) and `accept_words: reader` (L9). The vetoes are guardrails: they never decide what to offer or when to accept (L6).

## What our evidence doesn't cover yet

Every belief below is limited by this. Narrowing the list is itself progress.

- **Opponents:** no opponent stronger than local Qwen 27B (with or without thinking), and no other team's agent.
- **Our model:** Qwen 27B only. Effects of prompts and reasoning may differ, even reverse, on a stronger model.
- **Rules:** single-issue price, the free-text protocol, 5 to 10 rounds, private information. No clock pressure, no multi-issue deals.
- **Readers:** our own referee's reader. The tournament's reader is unknown.

## Strategy and the model

**L1. A strategy prompt is the biggest lever found so far, but its gain on dev mostly doesn't reach unseen opponents.**
- Status: holds.
- Visibility: internal.
- Evidence: prompt v2 gave +0.105 share over plain O1 on dev (pre-reset, p = 0.0001). The baseline was +0.117 over O1 on dev (p < 0.0001), but only +0.033 on the holdout (ns) and with 9 points fewer deals ([000](experiments/000-baseline.md)).
- Scope: Qwen against Qwen personas and scripted opponents; standard-v1 and holdout-v1.
- So: treat any dev gain as an upper bound until the holdout agrees.

**L2. Giving Qwen more to think about or more numbers each turn makes it settle for less.**
- Status: holds for the full digest, private analysis and thinking. The moves-only digest is the exception (suggestive).
- Visibility: public.
- Evidence (pre-reset): `analysis: true`, `qwen-local-think` and the full `state_digest` each led to more deals and less value per deal. [001](experiments/001-reciprocity.md): `state_digest: moves`, which leaves out the "their offer is $X better than your walk-away price" line, raised the deal rate from 68% to 78% at +0.033 (p = 0.18).
- Scope: Qwen 27B as our model.
- So: what the model is shown matters more than how much. A line framing their offer against our limit seems to invite settling for anything above it.
- Revisit if: our model changes.

**L3. Qwen doesn't follow a numeric concession rule, even with the numbers in front of it.**
- Status: suggestive.
- Visibility: public.
- Evidence: [001](experiments/001-reciprocity.md). The baseline concedes more than the other side's last move in 46–77% of its concessions. With the rule spelled out and the moves computed for it, this dropped only to 57–65%.
- Scope: Qwen 27B, standard-v1.
- So: prompting a concession policy harder won't make Qwen follow it. Changing what the model sees or how the decision is framed are still open.

**L4. We concede faster than firm opponents, and boulware beats us head to head.**
- Status: holds.
- Visibility: internal.
- Evidence: pre-reset league, 0.37 of the zone against boulware's 0.53 over 20 matches. League in [000](experiments/000-baseline.md): boulware first. [001](experiments/001-reciprocity.md): we give up 1.6–1.8 times as much as the hardliner and the tough persona over a match.
- Scope: Qwen-based agents against boulware, the scripted hardliner and the tough persona.
- So: the open question is how to hold firm without a coded schedule (L6).

**L5. Gains against scripted opponents don't carry over to LLM opponents.**
- Status: suggestive.
- Visibility: public.
- Evidence: [001](experiments/001-reciprocity.md): both finalists gained against scripted opponents only, and were level or behind against the tough and manipulator personas. idea-1: the parameter sweep's best settings looked overfit to scripted opponents.
- So: read the per-opponent split before believing an average. A gain carried by the scripted opponents is weak evidence.

**L6. Strategy stays with the model; code doesn't decide what to offer or when to accept.**
- Status: policy.
- Visibility: public.
- Why: a coded rule is a fixed pattern that an adaptive opponent can find and exploit. Pointing that way: idea-1's deterministic concession curve was learnable (analysis), and on unseen opponents the baseline did worst against one built to look for patterns, though not significantly ([000](experiments/000-baseline.md)).
- Scope: the exploit argument is untested against a truly adaptive strong opponent.
- So: see [06 §3.3](06-agent-contract.md#33-strategy-lives-in-the-model).

## Guardrails

**L7. Only a code veto keeps the agent within its walk-away price; a prompt can't.**
- Status: holds.
- Visibility: public.
- Evidence: the strategy prompt alone went past the limit in 11 of 240 dev matches (pre-reset). A limit-only veto still let 8 through. `limit+mentions` let 0 through, at +0.153 over plain O1 on dev and +0.131 on the holdout. Plain O1 went past its limit in 14 of 240 on dev and 4 of 120 on the holdout ([000](experiments/000-baseline.md)). idea-1: hard limits in code made liars and injectors score the same as honest opponents (offline).
- So: keep `limit+mentions`, or something at least as strict, in every agent. A price written in the text counts, even when rejecting it.

**L8. Every rule a veto adds beyond the hard limits costs deals.**
- Status: holds.
- Visibility: public.
- Evidence (pre-reset): O2's original `checks: all` (also no walking back offers, no stray prices) closed 58% of matches against 78%.
- So: vetoes guard invariants only. Each extra rule needs its own measurement.

**L9. The accept-words veto in `reader` mode costs nothing measurable.**
- Status: holds for no cost (−0.001, ±0.013 on 240 coupled pairs, pre-reset). `strict` mode: +0.001, ±0.036, but it rewrote two thirds of matches, so it is not shown to be harmless.
- Visibility: internal.
- So: keep `reader` mode. Don't adopt `strict` without a reason.

**L10. The deal rate we give up with vetoes is deals past our own limit.**
- Status: holds.
- Visibility: public.
- Evidence (pre-reset): counted within the agent's own limit, the vetoed agent closes as often as the unvetoed one.
- So: the deal check in the promotion rule counts deals within the agent's own limit only.

## Reading text

**L11. Regex readers can't be patched into correct ones; a model with a second read on acceptances does much better.**
- Status: holds.
- Visibility: internal.
- Evidence (pre-reset): each regex fix left a gap that persona opponents found (quoted prices read as offers, a bare "Deal." closing at a stale price, agreement words next to a refusal). On about 2,000 stored messages: 4 false acceptances for Qwen with a thinking second read, 13 for the rules, 36 for Qwen without the second read.
- So: benches read with the two-step model reader. Every misread found goes into `configs/referee/reading-corpus.yaml`, and `regateo reader-eval` scores readers against it.

**L12. A thinking reader needs its profile's full token budget.**
- Status: holds.
- Visibility: internal.
- Evidence (pre-reset): capped at 256 tokens, it ran out mid-thought, and the rules silently stood in.

**L13. Anything we write can be held against us: prices we mention, and agreement words.**
- Status: holds (L7, L9, L11).
- Visibility: public.
- So: since the tournament's reader is unknown, the agent should be safe under any reasonable reader, not just ours.

## Architecture

**L14. Hiding the opponent's text from the strategy also hides its true signals.**
- Status: suggestive (idea-1, analysis).
- Visibility: public.
- Evidence: idea-1's parser kept only intent, price and tactic labels. Real deadlines, final offers, conditional offers and plausible clues to the other side's limit were all lost, and the writer couldn't answer arguments or questions.
- So: since a match with no deal scores 0, misreading a real deadline can cost more than falling for a bluff. Label manipulation; don't throw the text away.

**L15. A fixed guess at a hidden deadline can't win both ways.**
- Status: holds (idea-1, measured offline).
- Visibility: public.
- Evidence: guessing 3 rounds lifted 4-round hidden-deadline games from 0.00 to 0.62, but cut 8-round ones from 0.48 to 0.36.
- So: estimate the deadline from evidence: platform metadata, the opponent's statements and their behaviour.

**L16. Splitting out a parser moves the attack surface into the parser; it doesn't remove it.**
- Status: suggestive (idea-1, analysis).
- Visibility: public.
- Evidence: a price planted in the text could be picked up by the parser. A big fake concession followed by a retreat skewed the opponent model.
- So: the opponent's numbers are adversarial input too, not only their prose.

## Measuring

**L17. Coupled pairs are what make small effects visible.**
- Status: holds.
- Visibility: public.
- Evidence (pre-reset): on 240 pairs, Δshare is known to about ±0.012 for a change that rarely fires, against ±0.05 with independent draws. Coupling broke twice: the subject's agent was in the replay key, and both sides of a pair missed the cache at the same moment.

**L18. A screen tier with "Δ > 0 goes on" is close to a coin flip for gains of 0.01–0.05.**
- Status: holds (pre-reset).
- Visibility: public.
- So: use successive halving on the full bench.

**L19. A safety change can't show a significant gain in share.**
- Status: suggestive.
- Visibility: public.
- So: judge guardrails on non-inferiority (the lower end of the range above about −0.02) plus the safety gain where the failure happens. This is not yet adopted as a rule.

## Tried and didn't help

<!-- visibility: internal -->

All of these were on Qwen 27B against the dev bench, on the strategy prompt's predecessor or the baseline's parent (L2 scope). Retry one only with a reason why a variation should work now, for example a stronger model.

| Change | Result | Entry |
|---|---|---|
| `analysis: true` (private notes before each decision) | Hurt: more deals, less value per deal | L2 |
| `model: qwen-local-think` (thinking on) | Hurt, the same way, and much slower | L2 |
| `state_digest: true` (summary of the offers each turn) | Hurt, the same way | L2 |
| `model: qwen-local-pp0` (no presence penalty) | No effect | |
| O2's original `checks: all` (also no walking back, no stray prices) | 58% deal rate against 78% | L8 |
| Prompt: accept when within 5% of the walk-away price | −0.027 (ns). It tells the agent to take deals worth almost nothing | |
| Prompt: never repeat an offer price | −0.036 on the screen. It contradicts holding firm | |
| `fence: true` (tag the other side's messages) | −0.021 on the screen | |
| Prompt v3: the reciprocity rule as a step before every offer ([001](experiments/001-reciprocity.md)) | −0.003 at 48 pairs | L3 |
| Prompt v3 + `state_digest: moves` ([001](experiments/001-reciprocity.md)) | +0.044, p = 0.09, gains against scripted opponents only | L3, L5 |
| `state_digest: moves` on the baseline ([001](experiments/001-reciprocity.md)) | +0.033, p = 0.18; deal rate 68% → 78%, no deals past the limit | L2 |
| Veto `accept_words: strict` | +0.001, ±0.036 | L9 |

## Open questions

<!-- visibility: internal -->

- Why does boulware beat us head to head, and do we concede faster than it near the deadline? (L4)
- What makes Qwen hold firm, if a stated rule doesn't? (L3)
- Do our beliefs hold against an opponent stronger than Qwen? (Every entry's scope.)
