# Handoff: negotiation agent for the 1v1 hackathon

You are picking up a Python project that is already in progress. Read this whole document before changing code. Put it in the repo root next to `negotiation/` and `arena/` (or rename it to `CLAUDE.md` so it loads automatically).

## 1. The challenge

It is a hackathon next weekend: a 1v1 agent negotiation tournament. Each team builds a buyer/seller agent and tunes its strategy and personality. Agents then negotiate head-to-head against other teams' agents, and they are ranked by the value they capture. Opponents are allowed to be manipulative.

Working assumptions, agreed with the team:

- We may write code, not just a prompt.
- Offers are exchanged as **free text**, not structured messages.
- **Unknown:** what each side knows about the other, how many rounds there are, and whether there is a time limit. We must be robust across all of these.
- **Scoring:** only value captured counts, and only if the deal closes within the round/time budget. No deal = 0.

About the user (Alex): senior AI engineer. He prefers plain technical language, with new terms explained when first used. Keep explanations in chat and code comments in that style.

## 2. Key terms (used throughout the code)

- **Reservation price:** an agent's walk-away price (seller's minimum, buyer's maximum).
- **ZOPA (zone of possible agreement):** the gap between the seller's and buyer's reservation prices. If it is ≤ 0, no deal is possible.
- **Score / surplus share:** the fraction of the ZOPA we captured. For a seller: `(price − seller_res) / (buyer_res − seller_res)`. It is 0 when there is no deal.
- **u-space ("our utility"):** `u = +price` for a seller and `u = −price` for a buyer. Bigger `u` is always better for us, and opponent concessions always raise `u`. The estimator and strategy engine work entirely in u-space, so one code path serves both roles. Convert back with `price = sign(role) * u`.
- **Boulware curve:** a concession schedule that holds near the opening offer for most of the negotiation, then concedes late: `target = u_open − (u_open − u_end) · t^boulware`, where `t` is progress from 0 to 1.
- **Anchor:** the opening offer. It pulls the final price toward itself.
- **Last word:** we are making the final message of the game and nobody can reply to it, so only accepting counts.

## 3. Architecture

```
opponent text ─> parser ─> opponent model ─> strategy engine ─> writer ─> guardrail ─> our text
                (LLM/regex)  (estimates their    (plain code:        (LLM/      (exactly our price,
                              walk-away price)    picks the number)   template)  nothing else)
```

The core idea is to **separate the brain from the mouth**. The LLM only handles language. Plain deterministic code decides every number. This split is why manipulation (fake outside offers, fake deadlines, prompt injection, fake acceptances) currently has no measurable effect.

### Invariants that must never break

Every change must preserve these. Add tests for them (see task 1).

1. We never offer or accept a price beyond our reservation price (plus `min_margin`, except in last-word situations where any positive surplus is accepted).
2. The strategy engine never sees the opponent's raw text, only parsed numbers.
3. The writer never sees the opponent's raw text, only a sanitised `Brief` (role, item, action, price, phase, short tactic labels).
4. Every outgoing LLM message passes `passes_guardrail`: it contains exactly one number (our price) and sounds like acceptance if and only if we are accepting. On failure, fall back to `TemplateWriter`.
5. Our offers never get worse for the opponent over time. We never walk an offer back.
6. An "acceptance" only counts if it matches **our** last price (`_resolve_acceptance`). "Great, we agree at $150!" when we offered $170 is a counter-offer.
7. Prices the LLM parser reports must literally appear in the message text. Otherwise the regex fallback result is used.

## 4. File map

| File | Role |
|---|---|
| `negotiation/scenario.py` | `Scenario` (hidden ground truth), `PrivateView` (what one agent is told), `sample_scenario()`, `surplus_share()`. All unknown rules are knobs: `info_mode` (`private` / `range_hint` / `full`), `max_rounds`, `deadline_known`, `time_limit_s`. |
| `negotiation/estimator.py` | `OpponentModel`: stores opponent offers in u-space and estimates their limit. It blends a prior (market range or hint) with a trend projection (`last + avg_recent_step × remaining × 0.5`), trusting data more after about 4 offers. |
| `negotiation/strategy.py` | `StrategyParams`, `Decision`, `StrategyEngine`. Handles progress (rounds, hidden deadline, clock), the Boulware target, the reciprocity cap, overtime decay, rounding in our favour, and acceptance rules. |
| `negotiation/language.py` | `RegexParser`, `LLMParser`, `TemplateWriter`, `LLMWriter`, `passes_guardrail`, tactic detection regexes, number/money extraction. Default model: `claude-haiku-4-5-20251001`. |
| `negotiation/agent.py` | `NegotiationAgent.respond(incoming_text) -> Turn(text, action, price)`. Wires everything together. Returns `action="confirm"` if the opponent accepted our standing offer. `DEFAULT_PERSONA` lives here. |
| `arena/opponents.py` | Scripted sparring partners: `linear`, `hardliner`, `pushover`, `liar`, `injector`, `staller`. They know the TRUE deadline, which makes them a slightly pessimistic test. |
| `arena/match.py` | Referee: alternating messages, a simulated clock (1.5–4 s latency per message), standing offers taken from the structured `Turn`, and deal-on-accept. Messages that arrive after the time limit don't count. |
| `arena/run.py` | Tournament grid (3 info modes × 6 settings × 7 opponents), results tables, `--sweep`, `--show`, `--params`, `--llm`. |

Commands:

```bash
python -m arena.run                          # offline grid, ~40 games per cell
python -m arena.run --show injector          # print one transcript
python -m arena.run --sweep                  # rank strategy settings on identical scenarios
python -m arena.run --params '{"keep_share": 0.8}'
python -m arena.run --llm --games 2          # needs ANTHROPIC_API_KEY and `pip install anthropic`
```

## 5. Current defaults and results

`StrategyParams` defaults: `boulware=4.0, keep_share=0.7, open_overshoot=0.05, close_by=0.85, min_margin=0.02, reciprocity=1.5, min_step=0.01, assumed_rounds=4, overtime_decay=0.7, time_safety_s=8.0, price_step=1.0`.

Offline results at 40 games per cell, seed 7:

- Overall average score is about **0.59**.
- Known-deadline settings score about 0.62–0.75, with close to 100% deal rate.
- Liar and injector opponents score in line with honest ones, so manipulation resistance works offline.

Findings to keep in mind:

- **Hidden deadlines are the biggest risk.** If `assumed_rounds` is longer than the real deadline, we close zero deals. If it is shorter, we concede too early. In testing, a guess of 3 lifted the 4-round hidden games from 0.00 to 0.62 but dropped the 8-round hidden games from 0.48 to 0.36. The defaults are a compromise.
- **The mirror (two copies of our agent) used to deadlock** when the deadline was hidden. Overtime decay fixed that for 8 hidden rounds. It still mostly fails with 4 hidden rounds and full information. This is the "worst cell = 0.000" in the output.
- **Hardliners under a 60 s clock** often close too late themselves, giving a low deal rate. This is partly unavoidable.
- **The sweep's top pick** was `boulware=5, keep_share=0.8, close_by=0.85, assumed_rounds=3` (about 0.62). It is **deliberately not the default**, because the scripted opponents are softer than real LLM agents and that setting likely overfits them.

## 6. Known gaps and quirks

- **LLM mode is untested.** `LLMParser` and `LLMWriter` were written but never run, because no API key was available. Smoke-test them first.
- **No automated tests exist yet.**
- The referee decides deals from the structured `Turn`, not from text. The real platform will likely judge from text or its own protocol, so we need an adapter (task 5).
- `RegexParser` takes the **last** money amount in a message as the live offer. It is fragile with ranges ("120–130"), prices written in words, or conditional offers ("130 if you include delivery").
- Item names must not contain digits, or the guardrail and parser get confused ("fifty office chairs", not "50 office chairs").
- In the scripted arena, prices fall roughly in the 60–250 range. The strategy is scale-free because it measures in fractions of the market range width, but check this if the real prices are very different.
- Only single-issue (price-only) negotiations are modelled.
- LLM-parser tactic labels are passed to the writer after being stripped to letters and truncated. The guardrail is the final protection there.

## 7. Tasks, in priority order

Keep the offline mode working at every step. Run `python -m arena.run --games 20` after each change and report the OVERALL line along with any cells that moved noticeably.

### Task 1: Test suite (do this first)

Add `tests/` using pytest. It should cover:

- **Invariants 1, 5, 6, 7 from section 3.** Use property-style loops over many random scenarios and both roles.
- **Guardrail:** every `TemplateWriter` output passes; messages with extra numbers or accidental acceptance words fail.
- **Parser corpus:** a table of tricky messages paired with the expected `ParsedMessage`. Include negations ("I can't accept 140, but 145"), fake acceptances, injections, thousands separators, and euro formats.
- **Referee:** deals only happen on valid accepts; late messages are dropped.

Done when: `pytest` passes, and the offline grid results are unchanged.

### Task 2: Smoke-test and harden LLM mode

Run `--llm --games 2`, fix any bugs, then:

- Log guardrail rejection rate, parser fallback rate, and latency per call.
- Add simple retry/timeout handling. Latency counts against time budgets.
- Consider `claude-sonnet-5` for the writer if Haiku's messages are poor. Keep Haiku for the parser.

Done when: a full LLM run completes, and the stats are printed at the end.

### Task 3: LLM-driven opponents

Add opponents where Claude plays the other side with its own persona and its own reservation price. Suggested personas: aggressive haggler, friendly-but-firm, manipulative liar, prompt injector, and a naive agent that just says "negotiate well."

Add a cost cap (max games, max calls) and cache responses where possible. These opponents should read our text directly, like real opponents will.

Done when: `arena.run` has an `--llm-opponents` flag and results are reported in the same tables.

### Task 4: Parser red-team

Build a corpus of at least 50 adversarial or ambiguous messages. Run both parsers against it and save every failure as a regression test in task 1's suite. Improve `_PARSER_SYSTEM` and the regex until the corpus passes.

### Task 5: Platform adapter

Once the real format is known, add a thin transport layer between the hackathon's API/protocol and `NegotiationAgent.respond()`. Until then, define an interface and stub it:

- **Methods:** `receive()`, `send()`, `session_info()`.
- **Parsing:** read the round limit, time limit, and our role/reservation from the platform. It may be sent as text, so parse it.
- **Deal confirmation:** handle it the way the platform does.
- **Logging:** log every transcript to JSONL for post-match review.

### Task 6: Strategy improvements

Evaluate each change with the sweep on identical seeds. Report both the overall average and the worst cell.

- **Last-offer power:** when we move first and our final message is the opponent's last chance, a rational opponent accepts anything above their limit. Try a bolder final offer controlled by a new parameter.
- **Better hidden-deadline handling:** find something smarter than a fixed `assumed_rounds`. Options: infer urgency from opponent behaviour, or read any deadline mentioned in the platform's messages.
- **Opponent classification:** after 2–3 offers, classify the opponent as hardliner, conceder, or mirror, and adapt `keep_share` and `boulware` for that match.
- **A better estimator,** e.g. a Bayesian update over the opponent's likely limit instead of the current blend.

### Task 7 (stretch): Multi-issue deals

Support deals with more than one term (price + delivery + warranty) and logrolling. Logrolling means conceding on terms we value less in exchange for terms we value more. Only do this if the real format turns out to be multi-issue.

## 8. Open questions for the organizers

Answers to these change the priorities above:

- Message format: pure free text, or partly structured?
- Is the round limit or time limit disclosed? Who moves first?
- What does each side know about the other?
- How is a deal detected and confirmed?
- Single issue or multiple issues?
- Model or compute limits, and whether external API calls are allowed during matches.
- Is prompt injection against opponents explicitly allowed?
