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

(pending)
