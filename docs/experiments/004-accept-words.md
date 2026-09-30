# 004: Can a veto on acceptance words stop misread acceptances without costing value?

**Bench:** standard-v1, full, coupled pairs, early stopping. **Reference:** o2/v2-limit-quiet.
**Config:** `backend/configs/gym/exp-004-accept-words.yaml`.

## Why

On the holdout, o2/v2-limit-quiet closed two deals past its own limit, and neither was the agent offering or accepting
past it ([002](002-limit-veto.md)). Both times it wrote a message meant to keep talking, "ready to ship the moment we
agree" and "I'm confident it's a solid deal for the right person", and the referee's rules reader took it as accepting
the other side's lowball. A tournament platform reading free text may do the same. That breaks requirement M2
(never close a deal by accident), and a stronger opponent could provoke it on purpose.

This is a guardrail, not strategy: the veto never decides what to offer or when to accept, it only stops a message that
doesn't accept from sounding like one.

## Variants

The veto (`accept_words` param on O2, `agents/baselines/o2.py`) gets the same one retry with feedback, then the move
is repaired in code.

| Challenger | Veto on a message that doesn't accept | Hypothesis |
|---|---|---|
| o2/quiet-words | what our rules reader would take as an acceptance | removes the misreads at almost no cost |
| o2/quiet-words-strict | any agreement word, negated or not ("can't accept", "deal", "agree") | also safe against a reader stricter than ours; may cost a little naturalness |

## What would change our mind

A drop in share or deals beyond noise means the rewording costs persuasion, and the guardrail should move to the
referee side instead (a stricter reader, a new bench version). Coupled pairs make this comparison unusually precise:
the challenger's match is identical to the reference's until the veto first fires.

## Results

### Full bench (run_01a0f1eca7c68f97180c, 240 pairs)

| Challenger | vs reference | p | Deals within own limit | Past own limit |
|---|---|---|---|---|
| o2/quiet-words | −0.020 [−0.070, +0.031] | 0.45 | 70% vs 70% | 1 |
| o2/quiet-words-strict | −0.044 | 0.09 | 68% vs 70% | 0 |

Neither gains; strict costs share (its veto fired in 156 of 240 matches) and fails the deal check.

**Not a clean measurement.** Coupling didn't work: only 3 of 240 pairs stayed identical, and 167 diverged at the
first message, because a pair's matches start together, both missed the cache and sampled apart. Fixed since
(`CachedClient` makes an identical request in flight wait for the first answer). The reader veto fired in only 11
matches, so a rerun with working coupling should measure it almost without noise.

**The one past-limit deal was a referee misread plus a veto gap.** The hardliner wrote "Take it or leave it: $132"
(restating our $132); rules v1 read it as nothing, and our "Deal." closed at its older $112, below our $127.80 limit.
The veto checked the price our decision named ($132), not the offer as read. Both are fixed: the veto checks both
(`o2.py`), and the `rules-v2` reader (bench `standard-v2`) never closes at a stale price.

### Rerun on standard-v2, coupling working (run_01a0f209513322a2fb07, 240 pairs)

| Challenger | vs reference | 95% range | Veto fired | Pairs identical to the reference |
|---|---|---|---|---|
| o2/quiet-words | −0.001 | [−0.013, +0.010] | 30 matches | 231 of 240 |
| o2/quiet-words-strict | +0.001 | [−0.034, +0.037] | 160 matches | 121 of 240 |

No deal past the limit for either, deals within own limit 67% for all three.

- **Coupling works.** Every pair that differs from the reference is one where the veto fired; before the fix, 237 of
  240 differed. The reader veto's range is ±0.012 at 240 pairs, against about ±0.05 uncoupled: a 4× narrower
  interval, worth about 16× the matches.
- **Both vetoes cost nothing measurable.** The reader veto is pinned within ±0.013 of the reference; the strict one
  rewrites two thirds of matches and lands within ±0.036.
- **The gain check can't pass a guardrail.** A change whose purpose is safety, with zero cost, never shows p < 0.05
  on share. For guardrails the rule should be non-inferiority: the lower end of the 95% range above −0.02, plus the
  safety gain it exists for, measured where the failure happens (here: misread acceptances on the holdout).
  By that rule the reader veto qualifies on dev (−0.013 > −0.02); the strict one isn't shown yet (−0.034).

### Holdout (run_01a0f213084c97b05285, holdout-v2, 120 pairs)

o2/quiet-words vs the reference: +0.000 [−0.031, +0.031], no deal past the limit for either, 72.5% deals for both.
**Not trustworthy yet:** the rules-v2 reader read the exploiter persona's "we're agreed on everything else, but I
still can't commit at that level" as accepting $3,800, closing a deal the buyer had refused. The exploiter is built
to use agreement words, so its pairings are the ones most affected (share 0.57–0.63, range ±0.32). This led to the
LLM-first reader (`llm-first:<profile>`, docs/04 §6), and holdout-v2 should be rerun with it before this result counts.
