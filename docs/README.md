# Design docs

Design documents for the new negotiation agent architecture. Nothing here is implemented yet.

We're in the preparation phase: exploring options and learning, not locking in a design. Principles are treated as hypotheses and refined as experiments come in.

## Index

| Doc | Status | Summary |
|---|---|---|
| [learnings/idea-1.md](learnings/idea-1.md) | done | What the first prototype got right and wrong, and what it implies for the next design |
| [01-problem-and-constraints.md](01-problem-and-constraints.md) | draft | The challenge, known facts, unknowns and their design impact, open questions for organizers, requirements |
| [02-architecture-options.md](02-architecture-options.md) | exploring | Design space axes, nine candidate architectures with the experiment that tests each, draft principles held as hypotheses |
| [03-candidate-pipeline.md](03-candidate-pipeline.md) | exploring | Target pipeline (sanitise → reader → state → router → strategist → veto → writer → checks), split-knowledge idea, open questions, build path from a collapsed O2 baseline |
| [04-hill-climbing.md](04-hill-climbing.md) | in use | How we hill-climb the agent: terms, promotion rule, dev/holdout/league benches, a lean automated loop on local Qwen, noise and cost, what to build |
| [experiments/](experiments/README.md) | running | How to run variants head to head, and a log of every experiment and its result |
| Design principles and threat model | later | Written once experiments tell us which principles are worth their cost |
