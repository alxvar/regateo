# 01: Problem and constraints

Status: **draft**. Update it as the organizers answer the open questions in §5.

## 1. The problem

We are building an agent for a 1v1 negotiation tournament at a hackathon.

- Each match puts our agent against another team's agent: one is the **buyer**, the other the **seller**.
- The agents exchange **free-text** messages until one accepts the other's offer, or until the round or time budget runs out.
- Teams are ranked by the **value they capture** across matches.
- Opponents are **allowed to be manipulative**: bluffs, fake deadlines, invented outside offers, prompt injection, fake acceptances.

## 2. Terms

- **Reservation price:** an agent's walk-away price (the seller's minimum, the buyer's maximum).
- **ZOPA (zone of possible agreement):** the range between the two reservation prices. If it is empty, no deal is possible.
- **Surplus share:** the fraction of the ZOPA we capture. For a seller: `(price − seller_res) / (buyer_res − seller_res)`.
- **Budget:** the round limit and/or wall-clock limit for a match.

## 3. What we know

| Fact | Source | Confidence |
|---|---|---|
| 1v1 matches, buyer against seller | challenge brief | high |
| Ranking is by value captured | challenge brief | high |
| No deal within the budget scores 0 | team working assumption | medium |
| Offers are exchanged as free text | team working assumption | medium |
| We may write code, not only a prompt | team working assumption | medium |
| Opponents may be manipulative | challenge brief | high |
| Opponents are other teams' agents, most likely LLM-based | inference | medium-high |
| Hackathon length: one weekend | challenge brief | high |

## 4. What we don't know, and why it matters

Each unknown below changes the design. We should stay robust across all of them until they are answered.

| Unknown | Possible values | Design impact |
|---|---|---|
| **Message format** | pure free text / partly structured / structured offer field | How much parsing we need, and whether a deal is judged from text or from a structured field |
| **Deal detection** | platform judges the text / explicit accept action / both sides confirm | How we phrase acceptances; whether a stray "deal" in our message could close a deal we didn't intend |
| **Round limit** | known / hidden / none | Our concession timing. A hidden deadline was idea-1's biggest weakness. |
| **Time limit** | none / per match / per message | Latency budget, how many LLM calls per turn, model choice |
| **Who moves first** | fixed / random / chosen | Anchoring, and who has the last word (the final message nobody can answer) |
| **Information each side has** | private only / hint about the opponent's range / full | How much we must infer about the opponent's limit |
| **Scale and currency** | tens to millions; $/€/other | Number parsing, rounding, formatting |
| **Issues** | price only / price + other terms (delivery, warranty, quantity) | Whether we need trade-offs across terms (conceding on terms we care less about for terms we care more about) |
| **Scoring detail** | surplus share / absolute value / win-loss; how a deal past our reservation is scored | Risk appetite. If a deal past our reservation scores negative (as in our simulator) or is disqualifying, those deals must be impossible. |
| **Tournament format** | round robin / brackets; how many matches; same opponent repeated? | Whether to optimise the average or the worst case; whether learning about an opponent across matches pays |
| **Compute rules** | any external API / organizer-provided model / no network; cost caps | Whether an LLM can be used at all during matches, which one, and how often |
| **Offensive manipulation** | allowed / forbidden / unspecified | Whether we may use persuasion tricks or prompt injection against opponents, or only defend |
| **Role assignment** | we play both roles / fixed role | Whether we need one agent that handles both roles |

## 5. Open questions for the organizers

1. Is the message format pure free text, or partly structured? Is there a separate field for the offer?
2. How is a deal detected and confirmed?
3. Are the round and time limits disclosed? Is there a per-message timeout?
4. Who moves first?
5. What does each side know about the other's walk-away price?
6. Single issue, or several issues?
7. How is scoring computed exactly? What happens with a deal past our reservation price?
8. What is the tournament format and how many matches are there?
9. Are external API calls allowed during matches? Any model or cost limits?
10. Is prompt injection or other manipulation *by us* explicitly allowed?

## 6. Constraints on us

- **Time:** one hackathon weekend of build time plus the prep before it. We prefer designs that ship something simple first and add capability in increments.
- **Latency:** if a time limit exists, every LLM call counts against it. Idea-1 assumed 1.5–4 s per message. Design for a small, bounded number of calls per turn.
- **Cost:** tournament volume is unknown. Keep a per-match call cap and a working fallback that makes no calls.
- **Reliability:** an API error, timeout or malformed model output must never lose a deal. Every LLM step needs a deterministic fallback.
- **Testability:** we need to compare designs before the event. That requires LLM-driven opponents and a referee that judges deals from text (see [learnings §3.7](learnings/idea-1.md)).

## 7. Requirements

Derived from the sections above. The principles doc (written after the architecture exploration in [02](02-architecture-options.md)) will refine these.

**Must**
- M1. Never agree to a deal past our reservation price, whatever the opponent says.
- M2. Never close a deal by accident: an acceptance from us is always deliberate and matches a price we chose.
- M3. Close a deal within the budget whenever the ZOPA allows a reasonable one, including when the deadline is hidden.
- M4. Handle both roles, any currency formatting, and wide price scales.
- M5. Degrade gracefully when the LLM is unavailable or slow.

**Should**
- S1. Capture a large share of the surplus against realistic LLM opponents, not only scripted ones.
- S2. Use honest signals from the opponent (deadlines, final offers, conditions) without being exploitable by fake ones.
- S3. Argue for our price: justify it, respond to arguments, answer questions.
- S4. Be ready to extend to multi-issue deals if the format requires it.
- S5. Log every match so we can review it.

**Could**
- C1. Adapt to each opponent's style within a match.
- C2. Use offensive persuasion or injection, if the rules allow it.
