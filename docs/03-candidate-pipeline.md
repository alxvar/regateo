# 03: Candidate pipeline

Status: **exploring**. This captures the pipeline design discussed after [02](02-architecture-options.md). It is the current *target shape*, not a commitment. We build towards it from a collapsed baseline (§6) and keep each stage only if measurement shows it earns its cost.

In terms of the options in 02, this pipeline combines:

- O3: an LLM that decides, calling code tools for advice,
- O7: simulation, optional and only on key turns,
- O2: a code veto on hard limits,
- O6: a critic check at the end, optional,

together with a reader stage and persistent state.

## 1. Shape

```
opponent text ─> SANITISE (code): fence off with per-turn tags, strip role/system markers, cap length
             ─> READER (LLM + code): offer, claims + credibility, manipulation labels, questions
             ─> STATE (code): facts + beliefs, alongside the full negotiation history
             ─> ROUTER (code): fast path, or full reasoning; per-turn compute budget
             ─> STRATEGIST (LLM + tools; simulation only on key turns) ─> strategy object
             ─> VETO (code): hard limits only
             ─> WRITER (LLM) ─> CHECKS: code (numbers, acceptance) [+ optional LLM check]
             ─> send, or retry once, then fall back to a template
```

## 2. Stages

### 2.1 Sanitise (code)

This step is structural, not semantic. It does three things:

- It wraps the opponent's text in tags containing a random value generated fresh each turn (e.g. `<opp_7f3a…>`). The opponent can't predict the value, so they can't forge the tags.
- It removes anything that looks like our tags, role markers or system markers.
- It caps the message length. This bounds cost and latency, and stops the opponent from flooding the context.

The original text is always kept in the log.

### 2.2 Reader

**The reader labels; it doesn't block.** Its job is to make the strategist more robust, not to fully protect it. We always reply, and every message may contain a real offer.

It separates two kinds of manipulation, because they need opposite handling:

| | Attacks on the machine | Attacks on the negotiator |
|---|---|---|
| Examples | prompt injection, fake system/organizer notices, format tricks, forged "verified" tags | bluffs, extreme opening offers, fake deadlines, invented outside offers, pressure |
| Carries real negotiating information? | almost never | often: a "fake" deadline might be real |
| Handling | **redact** or insulate (little is lost) | **keep and label** with a credibility estimate; the strategist weighs it |

There are three ways to deliver the labels to the strategist:

| Mode | Pros | Cons |
|---|---|---|
| Inline warnings around flagged sections | keeps context, cheap | forgeable unless they use the per-turn tags |
| Structured insulation (flagged content replaced by a structured summary) | strongest protection | redaction mistakes go unnoticed; review the originals in logs |
| Free-text note to the strategist | most flexible | leakiest: it's LLM output derived from hostile text, so an injection can pass through reworded |

Start structured, with fixed categories and short fields. The narrower the reader's output, the less an injection can carry through it. Add a free-text note only if evaluation shows we're losing information.

Why the reader helps, even though it doesn't block:

- **The layers differ.** The reader and the strategist are different prompts with different jobs, so a single message has to fool both. Generic injections aimed at "whatever LLM reads this" hit the narrow-task reader first.
- **The opponent pays a cost.** Rounds and time they spend on manipulation are rounds and time not spent negotiating. Our architecture being hidden from them helps a little, but we don't rely on it.
- **It's measurable.** We evaluate the reader like a classifier, with precision and recall on a red-team set of messages. False positives matter: labelling a real deadline as fake pushes us toward a no-deal.

### 2.3 State

State is kept **in addition to** the full negotiation history. It has two parts:

- **Facts, written by code:** offers from both sides, our commitments (e.g. "final offer"), turn number, time used.
- **Beliefs, proposed by the strategist, stored by code:** the opponent's type, how credible their claims are, our estimate of their limit, our estimate of the deadline.

Each belief records where it came from and when. That lets a wrong early read be revised instead of anchoring every later turn.

### 2.4 Router

Most turns don't need the full pipeline:

- **They accepted our standing offer:** confirm, no LLM call.
- **Clear final-turn decisions** (e.g. their offer beats our walk-away price and nobody can reply after us): a rule decides.
- **Everything else:** full reasoning.

The router also holds the per-turn compute budget. It spends more on high-stakes turns, usually the last few. This is the main way to control cost, more than removing stages.

### 2.5 Strategist

**This is the core, and it sees the opponent's text**, sanitised and labelled but not blind. It must be hardened on its own:

- opponent text is fenced with the per-turn tags,
- its instructions rank our rules above anything inside the fence,
- the reader's labels help, but they don't replace these measures.

It may call code tools, such as:

- an estimate of the opponent's limit,
- a concession schedule,
- a deadline belief,
- a check of whether an offer is allowed,
- market facts.

It outputs a structured **strategy object**. Draft v0:

```
action:          offer | accept | reject | ask | hold
price:           number | null
talking_points:  [short strings]      # arguments to make; code checks them for numbers
address_claims:  [claim ids]          # which of their claims to respond to
tone:            enum
commitments:     [...]                # e.g. "final offer"; these commit us, so they're recorded in state
belief_updates:  {opponent_limit_est, deadline_est, opponent_type, claim_credibility}
rationale:       string               # for logs only, never passed to the writer
```

The fields will evolve as evaluation shows what the writer and the logs need.

**Simulation** is an early idea, with no decision yet on whether or how it runs. The LLM opponent personas we need for evaluation are already opponent simulators, so building them once serves three uses, in increasing order of risk:

1. an evaluation arena (needed anyway),
2. an offline source of data for opponent models,
3. a live tool for the strategist ("how would a tough buyer respond to X?"), only on end-game turns and only if the latency budget allows.

### 2.6 Veto (code)

**Hard limits only:**

- never offer or accept past our walk-away price,
- an acceptance must match a price the opponent actually offered.

Open: is **never taking an offer back** a hard limit or a strategy choice? (See §5.)

On failure: ask the strategist again once, with feedback, then clamp or fall back to a safe action.

### 2.7 Writer

The writer turns the strategy object into a message. It sees the conversation, so it can respond to arguments and questions. Whether it also knows our walk-away price depends on the split-knowledge option (§3).

### 2.8 Checks

- **Code checks (always on):** the price in the message matches the strategy object, there are no stray numbers beyond a whitelist, and the message sounds like an acceptance only when we are accepting.
- **LLM check (optional):** "does this follow the strategy?" is too vague to be useful as stated. If we add one, it gets specific items: does the message leak our limit, commit us to anything not in the strategy object, or contradict an earlier offer? It stays out of the baseline and runs in log-only mode on recorded transcripts first, to count real catches against false alarms.

## 3. Candidate principle: split knowledge

If the strategist knows our walk-away price:

> The strategist knows the secret but never speaks to the opponent. The writer speaks to the opponent but never learns the secret.

The only path for a leak is then the strategy object, which is structured and can be code-checked (no numbers except whitelisted ones, never our walk-away price). The writer can still respond to the opponent's arguments. An injection that reaches the writer can at most produce a bad sentence, and the code checks catch a stray acceptance or wrong number.

This keeps idea-1's main protection without making the strategist deaf. It is a **hypothesis to test**: compare leak rate and score against a writer that does know the walk-away price.

## 4. Risks to watch

- **Latency:** a full turn could take 5–15 mostly sequential calls (≈8–30 s), which doesn't fit tight clocks. Mitigations: the router, smaller models for the reader and writer, simulation only on key turns.
- **Lost context between stages:** each handoff is a lossy summary. If the strategy object doesn't mention something, the writer won't address it.
- **Errors compound:** a reader mistake propagates through the state into every later turn. Belief provenance (§2.3) is the mitigation.
- **Too many knobs:** every stage adds settings to tune. That's why stages must be removable (§6).

## 5. Open questions

1. **Does the strategist know our walk-away price?** This decides whether split knowledge (§3) applies.
2. **Is never taking an offer back a hard limit?** It prevents erratic behaviour but removes a legitimate tactic.
3. **What compute budget per turn should we design for?** Calls, latency and cost; this depends on the time rules (see [01 §4](01-problem-and-constraints.md)).
4. **Which labelling mode does the reader start with?** Proposed: structured.
5. **Where does simulation run, if at all?** Proposed: offline first.

## 6. Build path: from a collapsed baseline to the full pipeline

**Step 0: collapsed baseline (O2).** One LLM call outputs the v0 strategy object plus the message; code applies the veto and the code checks. This is the full pipeline collapsed into one call, so it produces the same logs and structured decisions from day one.

Then pull stages out one at a time. Measure each step against the previous one on identical scenarios, and keep a stage only if it earns its cost:

| Step | Change | What we learn |
|---|---|---|
| 1 | Separate the writer from the strategist (optionally with split knowledge) | Does separation cost quality? Does split knowledge reduce leaks? |
| 2 | Add the reader (structured labels) | Does it improve robustness against manipulative opponents, and what do false positives cost? |
| 3 | Explicit state (facts + beliefs) | Does consistency across turns improve, especially in long matches? |
| 4 | Router + compute budget | Latency and cost savings, and whether score holds under clocks |
| 5 | Strategist tools | Does advice from code change decisions, and do those decisions improve? |
| 6 | Optional LLM check, log-only first | How many real catches against false alarms |
| 7 | Simulation (offline → end-game only) | Does looking ahead help in the end game? |

Every stage has a trivial pass-through version, so any combination can be ablated (switched off to measure its contribution).

**Prerequisite:** the evaluation arena (LLM opponent personas + text-based referee + cost-capped runner). Without it, none of these comparisons mean anything (see [learnings §3.7](learnings/idea-1.md)).
