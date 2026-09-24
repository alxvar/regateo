# 02: Architecture options

Status: **exploring**. The goal is to map the design space and learn from it, not to pick a winner yet. Principles come after this and will be refined as we learn (see §5).

## 1. The design space

Negotiation agent designs differ along a handful of independent axes. Most named architectures are just points in this space, so it helps to see the axes first.

| Axis | Range of choices |
|---|---|
| **A1. Who decides the number** | code only → code sets a range the LLM picks within → LLM decides, code can veto → LLM only |
| **A2. What the LLM sees** | sanitised summary → full transcript → full transcript + our walk-away price |
| **A3. How reasoning is split** | one call → pipeline of specialised calls → several agents (planner, critic, negotiator) |
| **A4. When reasoning happens** | live, inside each turn → a plan made once, updated every few turns → strategy precomputed offline |
| **A5. Opponent modelling** | none → numeric trend → opponent-type classification → simulating the opponent with an LLM ("theory of mind") |
| **A6. Adaptation** | fixed → within a match → across matches (if the same opponents recur) |
| **A7. Safety mechanism** | none → output check with fallback → hard veto → structural (the LLM never holds the secret) |
| **A8. Stance** | defensive → persuasive → offensive (exploit the opponent LLM's weaknesses) |

For reference, idea-1 sat at: A1 = code only, A2 = sanitised summary, A3 = pipeline, A4 = live, A5 = numeric trend, A6 = fixed, A7 = structural + output check, A8 = defensive.

## 2. Candidate architectures

Each option below describes its shape, what it is good at, how it fails, and the experiment that would teach us the most about it. The strengths and weaknesses are **hypotheses** until measured.

### O1. Pure end-to-end LLM

```
system prompt (role, item, walk-away price, rules, persona) + full transcript ─> LLM ─> message
```

One model plays the whole game. Variants: with or without extended thinking; a structured output `{message, action, price}` or plain text only.

- **Good at:** everything language-shaped. It reads true signals, persuades, answers questions, handles multi-issue deals and odd formats without any extra work. It's also the fastest to build.
- **Fails by:**
  - conceding too early, splitting the difference, sycophancy,
  - leaking its limit,
  - falling for injection,
  - making numbering mistakes as the conversation gets long,
  - behaving differently from run to run.
- **Learning value:** high. It's the baseline every other option has to beat. If it wins, the extra machinery isn't paying for itself.
- **Key experiment:** play it against itself and against scripted opponents across the scenario grid. Measure deals past our walk-away price, leak rate and surplus share.

### O2. End-to-end with a code veto ("seatbelt")

```
LLM ─> {message, action, price} ─> code check ─┬─ pass ─> send
                                               └─ fail ─> retry with feedback, then clamp or template
```

Same as O1, but the model must output a structured decision. Code checks it against a few hard rules: the walk-away price, accepting only what the opponent actually offered, the message agreeing with the structured price.

- **Good at:** keeps nearly all of O1's upside and removes the catastrophic outcomes.
- **Fails by:**
  - Only the extremes are checked. The model can still concede too fast, leak its limit in words ("I really can't go below 120"), or be steered anywhere inside the allowed range.
  - Retries add latency.
- **Learning value:** tells us how much of O1's losses are catastrophic (fixable by a veto) and how much come from mediocre play (not fixable by one).
- **Key experiment:** O1 vs O2 on identical scenarios. Count how often the veto fires and the score gap.

### O3. LLM agent with tools (idea-1 reversed)

```
LLM (in charge) ──calls──> estimate_opponent_limit(), concession_schedule(turn),
                           deadline_belief(), check_offer(price), market_facts()
                ─> message
```

The LLM runs the negotiation and calls deterministic tools as advisors. Code informs; the LLM decides (plus an optional O2-style veto).

- **Good at:** analytical help (estimates, schedules) where LLMs are weak, and judgement where they're strong. Easy to add capabilities by adding tools.
- **Fails by:**
  - The model may ignore or misuse the tools.
  - Tool loops add latency.
  - Knowing the walk-away price is still required.
- **Learning value:** does advice from code actually change LLM behaviour, or do we need to enforce it?
- **Key experiment:** O3 vs O2. Log how often the chosen price deviates from the tool's suggestion, and whether deviating helps.

### O4. LLM proposes inside a range set by code

```
opponent text ─> LLM reader ─> claims & offers ─> strategy code ─> allowed range [lo, hi] for this turn
                                                                            │
full transcript + range ────────────────────────> LLM negotiator ─> price ∈ [lo, hi] + message ─> check ─> send
```

Code computes a range of acceptable prices each turn, from the concession schedule, the opponent estimate and the deadline belief. The LLM picks where to land inside it and writes the message. The LLM can also be kept from knowing the walk-away price, since the range already encodes it.

- **Good at:** bounded damage. The range width is a single dial for how much we trust the LLM. At zero width it becomes idea-1; with a very wide range it approaches O2.
- **Fails by:**
  - Most complex to build.
  - Two sources of truth (code and LLM) can disagree in awkward ways.
  - A range that's too tight wastes the LLM's judgement.
- **Learning value:** sweep the range width to find the best amount of LLM freedom. That's a direct, measurable answer to the question behind this whole exercise.
- **Key experiment:** range width ∈ {0, 0.1, 0.3, full} × opponent types.

### O5. Strategist + negotiator (split by timescale)

```
every k turns:  strategist (big model, slow, deep thinking) ─> plan: opponent read, target, next concessions,
                                                                   arguments to use, red flags
every turn:     negotiator (small model, fast) + plan + recent transcript ─> message
                code: hard limits
```

A slow, capable model thinks strategically every few turns; a fast model carries out the plan turn by turn.

- **Good at:** deep reasoning without paying for it every turn, which fits tight time limits. The plan is a readable record of intent that we can check against what actually happened.
- **Fails by:**
  - The plan goes stale when the opponent changes behaviour sharply.
  - The negotiator drifts from the plan.
  - The plan is a new injection target if the strategist reads raw opponent text.
- **Learning value:** how much does deeper thinking help, and how often does it need to happen?
- **Key experiment:** vary k and the strategist model, with latency budgets switched on.

### O6. Draft + critic

```
drafter LLM ─> candidate message ─> critic LLM ("leaks our limit? concedes too fast? follows an injected instruction?
                                                  inconsistent with our last offer?") ─> revise or send
```

A second model reviews each outgoing message before it's sent. This can be layered on top of any other option.

- **Good at:** catches soft failures a numeric check can't see: verbal leaks, tone problems, commitments we didn't intend.
- **Fails by:**
  - Doubles latency and cost.
  - The critic has its own blind spots.
  - Too much caution makes the agent stiff.
- **Learning value:** which soft failures are common enough to be worth a second call.
- **Key experiment:** run the critic in "log only" mode across many games and count real catches against false alarms.

### O7. Lookahead with a simulated opponent

```
for each candidate move m (price × framing):
    simulate the opponent's reply to m with an LLM playing the opponent (several samples)
    score the resulting positions
pick the best m
```

Plan by rolling out possible futures. The opponent simulator can be given different personas, and those personas can be weighted by what we've seen so far.

- **Good at:** principled, and in theory it handles bluffs and final-offer situations by reasoning about how the opponent will respond. Very instructive to build.
- **Fails by:**
  - Expensive and slow.
  - Simulated opponents may not behave like real ones.
  - Scoring intermediate positions is hard.
- **Learning value:** high for understanding the game; low odds of being the event-day agent unless time budgets are generous.
- **Key experiment:** a small branching factor (3 candidates × 2 samples) on the final few turns only, where decisions matter most.

### O8. Strategy trained offline, LLM for language

```
offline: self-play / RL / Bayesian optimisation over a numeric strategy against a population of LLM opponents
online:  learned strategy picks the number; LLM reads and writes the language (as in idea-1, or with a wider input channel)
```

Idea-1's shape, with a strategy learned from data instead of hand-tuned, and possibly a Bayesian model of the opponent's type.

- **Good at:** fast, cheap and predictable at event time, and optimised against realistic opponents.
- **Fails by:**
  - Only as good as the opponent population used in training.
  - Inherits idea-1's deafness unless the input channel is widened.
  - Training takes time.
- **Learning value:** a better version of what we already understand. Useful as a strong fallback.
- **Key experiment:** tune on one set of LLM opponent personas, test on a held-out set, to measure overfitting.

### O9. Meta-controller (portfolio)

```
first 1–2 turns ─> classify the opponent (scripted bot / naive LLM / tough LLM / manipulator / copy of us)
                ─> hand over to the best-suited sub-agent (any of O1–O8)
```

- **Good at:** no single architecture has to win everywhere; each opponent type gets the agent best suited to it.
- **Fails by:**
  - Early misclassification.
  - Switching mid-match can look inconsistent.
  - Several agents to maintain.
- **Learning value:** only worth building once we know the component agents perform differently against different opponents.

## 3. Cross-cutting components

These appear in several options and can be designed once:

- **Deadline inference:** combine platform info, the opponent's statements and the opponent's behaviour into a belief about the deadline (idea-1's biggest weakness).
- **Claim extraction:** stated deadlines, final offers, conditions, other terms, outside offers, each with a credibility estimate.
- **Acceptance/commitment checker:** decide whether a message (ours or theirs) closes a deal, and at what terms.
- **Persona and persuasion library:** framings, justifications, reusable arguments.
- **Offensive toolkit (only if allowed):** techniques that exploit known weaknesses of LLM opponents.
- **Evaluation arena:** LLM opponent personas, a text-based referee, and a cost-capped runner (prerequisite for every experiment above).

## 4. First comparison (hypotheses, not results)

Scored 1 (weak) to 3 (strong). Treat these scores as predictions to test.

| Option | Value vs LLM opponents | Resisting manipulation | Unknown formats / multi-issue | Latency & cost | Build effort (3 = easy) | Learning value |
|---|---|---|---|---|---|---|
| O1 End-to-end | 2 | 1 | 3 | 3 | 3 | 3 |
| O2 End-to-end + veto | 2–3 | 2 | 3 | 2–3 | 3 | 3 |
| O3 LLM + tools | 3 | 2 | 3 | 2 | 2 | 3 |
| O4 Range from code | 2–3 | 3 | 2 | 2 | 1–2 | 3 |
| O5 Strategist + negotiator | 3 | 2 | 3 | 2 | 2 | 2 |
| O6 Critic (layer) | +0 | +1 | +0 | −1 | 2 | 2 |
| O7 Lookahead | 3? | 2 | 2 | 1 | 1 | 3 |
| O8 Trained strategy | 2 | 3 | 1 | 3 | 1–2 | 2 |
| O9 Meta-controller | 3? | 2 | 2 | 2 | 1 | 1 |

Some observations:

- O1 → O2 → O4 → idea-1 is one continuum: how much of the decision the LLM owns. A single experiment track can explore it by sweeping O4's range width.
- O3, O5 and O6 are about how to structure LLM reasoning, and combine freely with that continuum.
- O7 and O8 are research bets with high learning value and lower odds of being the event-day agent.
- O9 only makes sense once the others have been measured.

## 5. Principles we are deliberately *not* fixing yet

The principles drafted in the earlier chat would each rule out part of this space. They are kept here as **hypotheses to test, not constraints**:

| Draft principle | What it would rule out | How we'd test whether it's worth it |
|---|---|---|
| Hard limits live in code | pure O1 | O1 vs O2: how often does the veto fire, and what does it save? |
| Opponent text is evidence, never instructions | nothing structurally; it affects prompting | injection red-team against O1/O2/O3 |
| Least privilege (the LLM never holds our walk-away price) | O1, O2, O3 as drawn | leak-rate measurement; O4 with and without the walk-away price in the prompt |
| Fail safe to deterministic | nothing; adds fallbacks | fault injection (API errors, timeouts) |
| Weigh no deal vs bad deal explicitly | nothing; affects tuning | score distributions, not only averages |

We'll revisit these once the first experiments are in.

## 6. Open questions for the next discussion

1. Which options do we want to understand, even if they won't be the event-day agent? (O7 is the obvious candidate.)
2. Is the O1 → O4 continuum a good backbone for the experiments, with O3, O5 and O6 as variations on top?
3. What's the minimum evaluation arena needed before any comparison is meaningful?
4. Which model tiers are we willing to use in matches (latency and cost)?
