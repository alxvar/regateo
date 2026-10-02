# 04: Hill-climbing the agent

Status: **in use**. This covers how we make the agent stronger one measured step at a time, and when a challenger replaces the reference. The per-experiment mechanics (variant configs, freezing, the gym command) are in [experiments/README.md](experiments/README.md). This doc adds what they don't cover yet: a promotion rule, a holdout, an opponent pool that grows, and a loop that can run unattended.

## 1. Goal and what's missing

Our goal is an agent that captures more value than any other team's agent. We get there by hill-climbing: propose a small change, measure it against the current reference, keep it only if it wins.

The gym already handles the measurement: agent identity covers every prompt and setting, comparisons are paired, the cache replays unchanged agents for free, and benches come in a screen tier and a full tier. Three things are missing:

1. **A holdout.** We compare several challengers per round on the same bench, so the best of them will usually look better than it really is. Without a second bench, gains can't be told apart from overfitting to `standard-v1`.
2. **Opponents that get stronger.** The bench's six opponents never change. The tournament's opponents are other teams' agents, most likely LLM-based and stronger than Qwen personas.
3. **A written promotion rule.** Today "wins on the full bench" is the whole rule. It doesn't say what we give up for the gain (deal rate, safety, robustness against particular opponents).

## 2. Terms

- **Bench:** the fixed exam every agent sits. It fixes the opponents, the scenarios, the rules and a random seed, and is frozen once it has results, so scores from different weeks compare. Example: [standard-v1.yaml](../engine/configs/benches/standard-v1.yaml).
- **Cell:** one combination of rule settings within a bench. standard-v1 has two: deadline known and deadline hidden, both with 6 rounds and private information.
- **Pair:** the challenger and the reference each play the same scenario against the same opponent, in the same role, with the same seed. We compare their two scores. Pairing removes the luck of the draw: an easy scenario is easy for both.
- **Tier:** a subset of a bench's scenarios. The full bench is 2 cells × 10 scenarios × 6 opponents × 2 roles = 240 pairs. Tier `screen` uses the first 4 scenarios per cell: 96 pairs.
- **Share:** the fraction of the zone of possible agreement (ZOPA) an agent captured. 0 is a deal at our own limit, 1 a deal at the other side's limit. No deal scores 0. **Δshare** is challenger minus reference, averaged over pairs.
- **Reservation price:** each agent's own walk-away price, given by the scenario (and, we expect, by the tournament). Agents never see the ZOPA or the other side's limit; only the referee knows both, to score.

## 3. What we maximise

**Primary metric:** Δshare against the reference, on the bench's scored opponents. Since `standard-v2` those are the LLM opponents only: the scripted ones are gates (below), because gains against fixed scripts don't carry over to adaptive opponents (docs/05 L5). The tournament ranks teams by value captured, so this is the number that matters. Bradley-Terry ratings and win rates are diagnostics only.

### 3.1 Promotion rule

A challenger becomes the reference only if all of these hold:

| Check | Where | Rule | Why |
|---|---|---|---|
| Gain on dev | `standard-v2`, full bench, scored opponents | Δshare > 0 with p < 0.05 (`stats/paired.py`) | Screens and halving cuts are for dropping losers, never for promoting |
| Same direction on holdout | `holdout-v2` (§4), scored opponents | Δshare > 0; it need not be significant on its own | A significant gain on dev plus a gain on unseen opponents is strong evidence. Requiring significance twice would reject most real gains (§6) |
| Never past reservation | both benches, gates included | 0 deals past our walk-away price | Requirement M1. A hard gate, never averaged away |
| Gates hold | both benches' gate opponents | Δshare against each gate opponent ≥ −0.10 | Each scripted opponent tests one weakness (holding firm, fake claims, injection). A candidate may not trade one away for gains elsewhere. 0.10 because each has only 40 pairs on dev (§6) |
| Keeps closing deals | both benches, full runs | deals within its own limit ≥ reference's − 2 points | Otherwise it gains share by walking away, which scores 0 in a real match. A deal past the limit doesn't count: it already fails the gate above |
| Deals are real | `regateo readings RUN` | no new class of misread acceptances or offers | It must win by negotiating, not by exploiting the referee's reader |

**Warning, not a gate:** a scored opponent whose Δshare drops significantly (p < 0.05) or by more than 0.10. Each opponent has only 40 pairs on the full bench, so smaller drops are indistinguishable from chance (§6). A human reads the flagged transcripts and decides.

**Code guardrails, not code strategy.** The baseline's vetoes are code, and stays code: it never decides what to offer or when to accept, only blocks a move that breaks an invariant, and a stronger opponent makes that more valuable, not less. What to offer and when to accept stays with the model. A coded strategy rule (e.g. "accept anything within the limit in the last round") is a fixed pattern a strong adaptive opponent can find and exploit, and our Qwen opponents wouldn't show it.

## 4. Benches

| Bench | Contents | Used for | How often |
|---|---|---|---|
| `standard-v2` (dev) | Scored: 3 Qwen persona opponents. Gates: 3 scripted opponents (hardliner, liar, injector). 20 scenarios per cell, 6 rounds, deadline known or hidden; the stable model reader | Every round: successive halving on the full bench | Every round |
| `holdout-v2` | As holdout-v1 (new seed, items and price scale, 5 or 10 rounds; opponents dev never sees: an exploiter persona that looks for fixed patterns in our play, with and without thinking, a naive persona with thinking, O1 with the strategy prompt, and a fast-conceding boulware), plus gates: dev's scripted opponents with other concession curves and wording | Promotion candidates only | About once per promotion |
| `adversarial-v1` | Opponents a person wrote after reading some of our agents' code (`informed_by`): the scripted red-team attacks in `regateo.opponents.redteam` (echo, misquote, quote-accept, stonewall, anchor) and an LLM attacker (`redteam:llm`, Qwen with thinking and a brief of our agents' weaknesses). Echo, misquote, quote-accept and the LLM attacker each have a plain twin that makes the same moves in plain words (or, for the LLM, plays without the brief) and shares its seeds, so the report pairs them and shows what each attack costs. Never in dev or holdout: the gym refuses them there | Red-team checks a person reads, with `regateo signals RUN --by-opponent` | For promotion candidates (`configs/gym/redteam-01.yaml`) |
| `standard-v1`, `holdout-v1` | The previous versions: all six dev opponents scored; the model reader with a random tag (never replayed from the cache) | Comparing with results from before 2026-10 | Retired |
| `league` (arena round robin) | Every past champion, plus o1, o2, boulware and the strongest personas | After each promotion | Once per promotion |

All opponents run on local Qwen or in code (§8).

**Holdout rules.**
- Only the single best candidate of a round runs on the holdout.
- Nobody, human or proposer, reads holdout transcripts to find ideas for challengers. They are for checking results, not for mining failures. Once we do mine them, the holdout has become a second dev bench.
- After about 5 promotions, or as soon as the holdout has influenced a design choice, retire it into dev and write `holdout-v2`.

**The league** answers "does it beat all other agents", not just "does it beat the fixed six". Each champion joins the roster, so later challengers have to beat stronger and more varied play. If a new champion loses to an old one head to head, we are going in circles and should find out why before the next round.

## 5. The loop

### 5.1 One round

1. **Mine failures.** From the reference's last full dev run, take the pairs with the most *regret*: where another of our agents in the same run got the most more than the reference did, on the same scenario, opponent, role and seed. The better agent's transcript goes next to the top ones. Ranking by regret instead of by share skips matches nobody could win; deals past either side's limit don't count as doing better. Group them by cause, for example opened too soft, conceded to a fake deadline, lost track of the numbers, or accepted an injected instruction. The "Why" section of [05-learnings.md](05-learnings.md) is this step done by hand.
2. **Propose 4–8 challengers.** Each changes one lever, is a small `extends:` config, and carries a hypothesis tied to one failure group.
3. **Successive halving on the full dev bench** (§6), with early stopping. Every challenger plays the first 48 pairs; the better half by mean gain plays on to 96, and so on until two are left, who finish all 240. The reference replays from the cache, so only challengers use the GPU.
4. **Combine.** Winning levers don't always add up, so when two win, also run one challenger that combines them.
5. **Holdout, guardrails and reading audit** (§3.1) for the best candidate.
6. **Promote.** `regateo freeze` its files, update "Current reference" in the experiments README, add it to the league roster, run the league, and write up `NNN-*.md`, null results included.

**Time budget.** In exp-001, each new match took about 3 s of wall time at concurrency 32, so a challenger's screen takes about 5 minutes and the rest of its full bench about 7. A round of 4 challengers comes to about 45 minutes:

| Step | Matches | Time |
|---|---|---|
| Screen, 4 challengers | 4 × 96 | ~20 min, less with early stopping |
| Rest of the full bench, 1–2 challengers | 1–2 × 144 | ~7–15 min |
| Holdout, 1 challenger | ~100–240 | ~5–12 min |

That is about 10 rounds overnight. Fewer challengers per round keeps rounds short without making each measurement noisier.

### 5.2 Automating steps 1–4

Steps 1–4 run without us. Step 5 and the promotion stay a human decision, because that is where overfitting gets in.

A mid-size local model is unreliable at long, multi-step tool use, and an unattended loop will hit its failures. So the proposer is **a script with one LLM call, not a coding agent**:

1. **`regateo mine RUN` (code, no LLM).** Picks the reference's worst pairs, groups them by opponent and end reason, and writes a bundle: the gym report, about 10 of the worst transcripts, and our agent's current prompt and config.
2. **Propose (one Qwen call, structured output).** Input: the bundle. Output: 4–8 challengers, each with a hypothesis, an `extends:` config, and optionally a new prompt version.
3. **Validate (code).** The configs load; only our agent's params and prompts changed; the frozen-files test passes. A proposal that fails is dropped, not repaired.
4. **Run** `regateo gym` on the proposals, and write the stub experiment doc.

Changes that need new code, such as a new pipeline stage, are proposed and built by us, not by this loop.

If we later want a real agent harness here, Pi or OpenCode can use vLLM's OpenAI-compatible API directly; Claude Code needs a translating proxy (e.g. LiteLLM) in front of vLLM. The isolation below then has to be enforced with a separate checkout or container, not by construction.

### 5.3 What the proposer may see

The proposer sees exactly what is in the bundle, so isolation holds by construction:

| May see | Must not see |
|---|---|
| Our agent's prompts and config | Persona prompts (`prompts/persona_*.md`) and opponent code (`agents/opponents/`) |
| Dev transcripts, including opponent messages: that is what our agent sees live | Anything from the holdout |
| The gym report for dev runs | Referee code and bench files |

The only files it may add are new agent configs, and new versions of the agent that differ from their parent in one prompt.

Dev transcripts still reveal how the scripted opponents behave, and those are deterministic, so the proposer can overfit to them. The holdout's different opponents are there to catch that.

During matches, agents are already isolated: each gets its `PrivateView` and the messages, nothing else.

### 5.4 A round over several architectures

For the hackathon plan ([07](07-hackathon-plan.md)) the round runs over several architectures at once, one line per architecture, with a Claude Code session per line instead of a proposer call (`regateo.climb.round`):

1. **Export** (`regateo round export RUN --candidate <config> ... --out DIR`): for each candidate, its last dev run's results, a workspace with only what its session may see ([06 §5](06-agent-contract.md#5-what-a-builder-may-look-at)): a copy of its architecture with the journal, its own matches and results, an anonymous leaderboard (Δshare of every agent, names hidden), the public learnings, the contract, and a `.venv` with only the agent SDK and pytest.
2. **Sessions**, in parallel (`engine/scripts/claude_builder.sh WORKSPACE`): Claude Code in bubblewrap, with that workspace and nothing else. It studies the results and writes up to 3 variants of its candidate, as new configs or a new version, plus a journal entry. It can run the agent's tests and the submission check; it can't run matches.
3. **Collect** (`regateo round collect DIR/* --name round-NN --reference <agent>`): takes new versions, new configs and the journal entry back into `agents/`, and refuses changes to existing versions or `lib/`, versions that fail the submission check, configs that don't resolve or crash in a smoke match on a fake model, and edits to earlier journal entries. Then it writes the round's gym config: every line's parent and variants against the reference, with successive halving within each line down to one finalist.
4. **The gym run** (`regateo gym round-NN`), then **record** (`regateo round record RUN`): each line's finalist becomes its next parent (a variant only if it beat its parent), and every architecture's journal gets the round's results.

Each session's results stay in its line: nothing it sees comes from another architecture except the anonymous leaderboard and the public learnings.

## 6. Noise and cost

Noise on Δshare shrinks with the square root of the number of pairs, so halving it costs 4× the matches. From the exp-001 and o2-vs-o1 full runs:

| Pairs | Noise on Δshare (95%, ±) | Smallest gain we can reliably see |
|---|---|---|
| 40 (one opponent within the full bench) | ~0.12 | ~0.15 |
| 96 (screen) | ~0.08 | ~0.10 |
| 240 (full) | ~0.05 | ~0.06 |
| 480 (a future `standard-v2`, 20 scenarios per cell) | ~0.035 | ~0.04 |

For example, in the full exp-001 run, o1-v2 gained +0.105 (p = 0.0001), clearly real, while o1-informed-v2's +0.026 (range −0.022 to +0.075) can't be told apart from nothing.

This sets the strategy:
- **Early on, gains are large,** and the screen plus the full bench are enough.
- **When easy wins run out,** add `standard-v2` with about 20 scenarios per cell, instead of more challengers. The reference then has to be re-run once on the new bench.
- **Early stopping, only to drop losers.** The gym checks each challenger every ~24 pairs and stops one that is clearly behind the reference. It never promotes early: checking repeatedly for a winner produces false winners.
- **Successive halving** instead of a screen (`halving: true` in a gym config). A screen that passes anything with Δ > 0 at 96 pairs is close to a coin flip for gains of 0.01–0.05 (±0.08 noise); exp-003's accept-tolerance went from +0.013 on the screen to −0.027 on the full bench. Halving spends the same matches on more candidates and gives the most to the close ones: 8 challengers cost 8 × 48 + 4 × 48 + 2 × 144 = 864 matches, against 1,056 for a screen of 8 plus a full bench for 2.
- **Coupled pairs** (on by default in benchmark gyms, `coupled: false` to turn off). The challenger and the reference share a pair's random draws: an identical request replays the same answer from the cache, and every call is sampled with a seed derived from the pair, the speaker and the turn. Their matches stay identical until their behaviour first differs, so a change that rarely fires, such as a veto, is measured almost without sampling noise. For prompt edits the gain is smaller: a different prompt samples different words even with the same seed. Turning it on changed every benchmark replay key once, so each reference plays its bench once more.
- **Settings we can't observe yet.** [01 §4](01-problem-and-constraints.md) lists unknowns such as a hidden deadline, structured or free-text offers, or several issues. Keep bench cells split along the ones we can simulate (as `deadline_known` already is), so a gain in one setting can't hide a loss in another.
- **Referee drift.** Changes to the referee's reader change scores for every agent. The reader is recorded in the bench (as now); a reader change means a new bench version.
- **Reading free text.** Regex rules kept misreading messages (002's quoted prices, 004's stale "Deal.", the holdout exploiter's "we're agreed on everything else, but I can't commit"), and each fix was a patch for the last phrasing. The reader moves to a model: `llm-first:<profile>` reads every free-text message, told that "accept" closes a deal and to answer it only when certain; its answer must be an amount the message names or the other side's offer; rules stay as a logged cross-check. Every reader is scored on a labeled corpus of real misreads (`configs/referee/reading-corpus.yaml`, `regateo reader-eval`), counting false acceptances, the costly error, separately. First scores, 37 cases: rules-v2 35 right with 1 false acceptance; `llm-first:qwen-local` 35 right with none (its two misses read a range as one of its ends); `llm-first:qwen-local-think` 36 right with none, but about 6 s a message against under 1 s. (A first thinking score of 36 with 1 false acceptance was an artifact: the reader capped answers at 256 tokens, thinking ran out, and the rules stood in. The eval now counts such fallbacks.)

## 7. What is built

| Piece | Where |
|---|---|
| Walk-away veto for the climbing line | O2's `checks` param: `limit` (never offer or accept past the limit) or `limit+mentions` (also never write a price past it); tested in [05-learnings.md](05-learnings.md) |
| Holdout bench | `engine/configs/benches/holdout-v1.yaml`, `purpose: holdout`; persona `exploiter` |
| League | `engine/configs/arena/league.yaml`; `regateo arena league` |
| Promotion checks in the gym report | "Promotion checks" section per challenger: gain (by bench purpose and tier), limit, deals, per-opponent warnings |
| Early stopping | `early_stop: true` in a gym config (`gym/early.py`): checks each challenger from 48 pairs, then every 24; stops it when mean + 2.58 × standard error < 0 |
| Failure mining | `regateo mine RUN` (`climb/mine.py`): ranked by regret, with contrast transcripts; refuses holdout runs |
| Successive halving | `halving: true` in a gym config (`gym/early.py`, `gym/run.py`); climb rounds use it |
| Coupled pairs | `MatchJob.couple` and per-call seeds (`runner/runner.py`); `coupled` in a gym config, on by default |
| Proposer | `regateo propose RUN --parent AGENT` (`climb/propose.py`), model profile `qwen-local-propose` |
| Unattended rounds | `regateo climb RUN --parent AGENT --rounds N` (`climb/loop.py`): propose, then one halving run |
| Promotion checklist | [experiments/README.md](experiments/README.md) |

## 8. Decisions and open questions

**Decided:**
- No API-based models for now, in matches, benches or the proposer. Everything runs on local Qwen or in code.
- The holdout must show a gain in the same direction, not a significant one (§3.1).
- A per-opponent drop is a warning for a human to read, not an automatic veto (§3.1).
- Rounds stay lean: successive halving with early stopping on the full bench, holdout only for the best (§5.1, §6). *Changed 2026-09-30: the screen tier was too noisy to pick winners.*
- The proposer is a script with one LLM call, not a coding agent (§5.2). *Revisited 2026-09-30: next, try Claude Code (Sonnet 5.5) in a sandbox, measuring what it uses of the subscription allowance.*
- The deal-rate check counts only deals within the agent's own limit, and applies only to promotion runs (§3.1).
- Guardrails in code, strategy in the model (§3.1).

**Open:**
1. When the organizers answer the open questions in 01 §5, which benches do we rebuild, and which results do we keep?

## 9. Where we are

1. **Clean start, 2026-09-30.** Experiments 001–004 were cleared; what they taught is in [05-learnings.md](05-learnings.md).
   The reference is `baseline` (strategy prompt plus the limit and acceptance-word vetoes); benches `standard-v1` and
   `holdout-v1` read messages with the two-step model reader. The baseline's first runs measure it against plain O1.
2. Built: the promotion checks, early stopping, successive halving, coupled pairs, regret mining, `regateo propose` and
   `regateo climb` on local Qwen, a repeat check on proposals, `regateo workspace`/`adopt` and a sandbox script for a
   Claude Code proposer, the model reader and `regateo reader-eval`.
3. Next: find out why boulware beats the reference head to head; try the Claude Code proposer; decide whether
   guardrails are promoted on non-inferiority.
