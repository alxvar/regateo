# 07: Hackathon plan

Status: **draft**. How we use the weekend: what we prepare before it, what runs unattended overnight, which model runs where, and when people decide. Update it when the organizers answer the open questions in [01 §5](01-problem-and-constraints.md#5-open-questions-for-the-organizers).

## 1. The weekend

| Day | On site | Unattended |
|---|---|---|
| Friday | 19:00–23:00 | Night 1: 23:00–09:00 |
| Saturday | 09:00–23:00 | Night 2: 23:00–09:00 |
| Sunday | 09:00–15:30, then the tournament, results and demos | |

About 2–3 hours go to understanding the requirements and adapting the platform on Friday, and another 2–3 hours to preparing for the tournament on Sunday. That leaves no room to hill-climb from one agent with small tweaks.

The plan instead:

1. Start from **several architectures, each with a few config variants**.
2. **Narrow them to the most promising within about 14 hours**, ending Saturday midday.
3. **Tune at most 3** until Sunday morning.
4. **Settle on one** with manual adjustments.

Night 1 searches and night 2 tunes. People decide in between.

**Models.** The hackathon is organized by Claude Community Madrid, so we expect API credits for Claude models, and our tournament agent will most likely run on Claude. The opponents, other teams' agents, most likely will too. Searching on Claude is too expensive for the credits we expect (§2.2), so we **search on local Qwen and confirm on Claude** (§2.3). Whether Qwen results carry over to Claude is checked before the event (§3 step 4).

## 2. Compute and cost

### 2.1 Local Qwen

Qwen runs on one RTX 5090 in a PC at home, reached remotely (§7.3). Our runs so far give the throughput:

| Run | Matches | Time | Per hour |
|---|---|---|---|
| exp-001 (3 challengers, halving) | 768 | 34 min | ~1,350 |
| baseline vs o1 (full bench) | 480 | 23 min | ~1,250 |

These are agents making one model call per turn, including the referee's reader calls. An architecture with 2–3 calls per turn will run at about half to a third of that. We measure each architecture's real throughput before the event (§3).

| Window | Hours | Matches (estimate) |
|---|---|---|
| Night 1 search, Fri 22:00 → Sat 12:00 | 14 | 10–18k |
| Night 2 tuning, Sat 23:00 → Sun 09:00 | 10 | 7–13k |

What that buys:

- **Cutting by successive halving is cheap.** 40 candidates down to the best few is about 4,000 matches (3–4 hours): 40 × 48 pairs, then 20 × 48 more, then 10 × 96, then 5 × 48.
- **A proposer round is expensive:** about 45–60 minutes for one candidate (mine, propose about 6 challengers, halving on the full bench). Adapting 40 candidates for 3 rounds each would take about 100 hours; even 10 candidates for 2 rounds takes about 17.

So we **cut first and adapt only the survivors**. The config variants within each architecture already give every architecture a fair chance before the cut.

### 2.2 Claude

From the baseline's dev run, our agent's side of one match is **about 7.3 model calls** (6 turns plus veto retries), **6.7k input and 0.45k output tokens**. Prompts are short, so prompt caching saves little, and the Batch API's discount doesn't apply because each turn waits for the reply before it.

| Our agent on | Assumption | Per match |
|---|---|---|
| Haiku 4.5 ($1 / $5 per MTok) | no thinking | ~$0.01 |
| Sonnet 5.5 ($2 / $10) | thinking off (`between_tools`) | ~$0.02 |
| Opus 5.5 ($4 / $20) | thinking can't be turned off; `low` effort, 300–800 thinking tokens a call | $0.07–0.15 |
| Fable 5.1 ($10 / $50) | thinking always on | $0.18–0.36 |

The counts are Qwen's tokenizer; Claude's may be up to about 35% higher. The thinking volume on Opus is the biggest unknown: a 20-match pilot (about $2) measures it.

The whole plan is about **24k matches**: night 1 about 13k, Saturday about 3k, night 2 about 6k, Sunday about 1.5k. Run entirely with our agent on Claude:

| Our agent on | Whole plan, agent side only |
|---|---|
| Haiku 4.5 | ~$250 |
| Sonnet 5.5 | ~$450 |
| Opus 5.5 | $1.7–3.6k |
| Fable 5.1 | $4–9k |

Multiply by 2–3 for architectures with several calls per turn. Opponents and the reader on Claude as well would add about $0.03 a match, about $700.

Three things change on the API:

- **Rate limits.** At about 50 requests a minute, a low-tier org plays about 7 matches a minute, slower than the local GPU. Ask the organizers which tier the credits come with.
- **Noise.** Claude takes no seed, so coupled pairs share answers only until the two sides first differ. Expect about ±0.05 on Δshare at 240 pairs instead of ±0.012 ([04 §6](04-hill-climbing.md#6-noise-and-cost)): plan for more pairs, or for telling apart only larger gains.
- **Latency.** Opus thinks before every reply. If the platform has a per-message time limit, that may choose the model before cost does.

### 2.3 The split

| Phase | Our agent | Opponents and reader | Matches | Cost |
|---|---|---|---|---|
| Night 1 search, Saturday tuning, night 2 tuning | Qwen | Qwen | ~22k | free |
| End of night 1: re-rank the top ~6 | Claude | Qwen | ~1.7k | Sonnet ~$35, Opus $120–250 |
| End of night 2: fresh-seed verification of the 3 lines, then the holdout on Sunday | Claude | Qwen | ~1.1k | Sonnet ~$25, Opus $80–170 |
| Proposer, about 30 rounds | Claude Code or Opus | | | ~$40 |

That is about **$100 with our agent on Sonnet, or $250–450 on Opus**. Opponents and the reader stay on Qwen, so credits only pay for our agent's side, plus the Claude opponents in §3 step 4 if the credits allow it at the event too.

If the transfer check (§3 step 4) fails, the search has to run on Claude: narrow the shortlist to 4–5 before the event, and run both nights on the API under `--budget` caps.

## 3. Before the event

The broad search happens here, where time is not short. At the event, night 1 only re-ranks a shortlist under the real requirements.

1. **Build the architectures.** Each one is built to [06-agent-contract.md](06-agent-contract.md), in its own session or worktree. Each has config axes: strategy guide, personality, manipulation on or off. Architectures should be mostly invariant to the requirements we don't know yet, so that only their configs change at the event. The model is always a param.
2. **Run the full grid on Qwen on the current benches**, over as many nights as it takes:
   - Measure matches per hour for each architecture, so the event's night plan has real numbers.
   - Find out which config axes matter at all, and drop the ones that don't.
   - Record what we learn in [05-learnings.md](05-learnings.md), as for any experiment.
3. **Choose a shortlist of 8–12 candidates** (architecture + config). It must cover every architecture family, not just the top scorers. Requirements we don't know yet can reorder the ranking, and the shortlist is our hedge against that.
4. **Check that Qwen results carry over to Claude.** This decides whether searching on Qwen is worth anything. It costs our own money (about $35–250) unless credits arrive early.
   1. Run a 20-match pilot per model we might use, to measure real tokens per match, thinking included, and correct §2.2.
   2. Pick about 6 shortlisted candidates spanning the range on Qwen, best to worst.
   3. Run each on the full dev bench with our agent on Claude, on the model we'd use in the tournament.
   4. **They agree** when the rankings correlate, at least 2 of the top 3 overlap, and no clear gap flips. Then search on Qwen as in §2.3. Otherwise, follow the fallback at the end of §2.3.
   5. In the same run, add 1–2 opponents powered by Claude. Tournament opponents will most likely be Claude-based, and we have never benched against anything stronger than Qwen ([05](05-learnings.md#what-our-evidence-doesnt-cover-yet)).
   6. Record the result in 05 as a learning, with its scope.
5. **Make requirement adapters.** Every unknown in [01 §4](01-problem-and-constraints.md#4-what-we-dont-know-and-why-it-matters) gets a switch or config that is already built and tested:
   - message format: structured or free text (`TurnProtocol`);
   - deal detection; round limit known, hidden or none; clock; who moves first;
   - information mode; price scale and currency;
   - multiple issues (at least a fallback);
   - the model our agent runs on: model profiles for Sonnet 5.5, Opus 5.5 and Haiku 4.5 next to `qwen-local`.

   A bench generator rebuilds the dev bench and the holdout from the stated rules in under an hour. This is what makes 2–3 hours on Friday enough.
6. **Make the home PC reachable** (§7.3), and test it from outside the home network.
7. **Build the tooling in §8.**
8. **Rehearse.** One full dry run with made-up requirements, run remotely as at the event: Friday's adaptation, a night including its Claude phase, the morning report, the cut. Fix whatever breaks.

## 4. At the event

### Friday

| Time | What |
|---|---|
| 19:00–22:00 | Understand the rules. Answer what we can of [01 §5](01-problem-and-constraints.md#5-open-questions-for-the-organizers), including the credit amount and rate tier. Switch the adapters, generate the event's dev bench and holdout, smoke-test every shortlisted candidate on Qwen and on Claude. |
| 22:00 | Start night 1. Watch the first halving step run before leaving at 23:00. |

### Night 1: search

1. **Re-rank** the shortlist on the event dev bench on Qwen with successive halving (about 3 hours).
2. **Adapt** the top ~6 on Qwen: 2 proposer rounds each (about 6–8 hours).
3. **Re-rank the top ~6 on Claude** (about 1.7k matches; 1.5–4 hours depending on the rate tier), so the results are ready by morning.
4. **League** on Qwen: a round robin among the survivors, plus boulware and the strongest personas.
5. **Morning report** (§8).

### Saturday

| Time | What |
|---|---|
| 09:00–12:00 | Read the report and the top candidates' transcripts. Run the holdout once on the top ~5. **Cut to 3**, from different architecture families unless one is clearly ahead beyond noise. Where Qwen and Claude disagree, Claude decides. |
| 12:00–23:00 | Tune by hand, with automated rounds in between. Add our 3 finalists to the bench as opponents: the tournament is other teams' LLM agents, and our own candidates are the closest thing to that we have. |
| 23:00 | Start night 2. |

### Night 2: tuning

1. About 3 proposer rounds per line on Qwen. A round's winner may become its line's parent for the next round if it passes the dev checks of [04 §3.1](04-hill-climbing.md#31-promotion-rule). Building on results nobody has confirmed is acceptable only because the next step checks everything again on fresh data.
2. **Fresh-seed verification on Claude** of each line's best, with no cache reuse (about 720 matches). After about 100 comparisons over two nights, the top scores are inflated by selection, and only new draws give an honest estimate.
3. **Morning report.**

### Sunday

| Time | What |
|---|---|
| 09:00–12:30 | Read the verification. Run the holdout once more on Claude, and a league among the 3. Pick one, make manual adjustments, re-check each one on Claude. **Freeze by 12:30.** |
| 12:30–15:30 | Tournament preparation: package the agent, test latency against the real platform, check the fallbacks, prepare the demo. |

## 5. Choosing between candidates

- **Primary:** Δshare against the reference, as in [04 §3](04-hill-climbing.md#3-what-we-maximise). On the tournament's model when we have it: Claude results outrank Qwen results.
- **Robustness gate:** a candidate significantly behind against any single opponent or rules cell is out, however good its mean. We are ranked against agents we haven't seen, so a weak spot matters more than a slightly higher average.
- **Hard gate:** no deal past our own limit (L7).
- **Diversity:** when finalists are within noise of each other, prefer different architecture families. Two prompts on one architecture fail the same way.
- **Holdout:** used on Saturday morning and Sunday morning only, results only. Nobody reads its transcripts ([04 §4](04-hill-climbing.md#4-benches)).

## 6. Why the nights run unattended

In [04 §5.2](04-hill-climbing.md#52-automating-steps-14) promotion stays with a person, because that is where overfitting gets in. That still holds: people make the cut on Saturday and the final pick on Sunday. Between those decisions, the nights choose without anyone present. The concerns about open-ended unattended climbing don't hold here:

| Concern | Here |
|---|---|
| False winners pile up over many comparisons | Each night ends in a human review. The fresh-seed verification and the holdout catch inflated scores. |
| Prompt tweaks are an exhausted search space (L1–L3) | The search is over architectures, which nobody has explored yet. |
| Unreviewed learnings drift over many nights | Two nights is too short for drift to compound. Learnings are drafted, not accepted, as in §8. |
| Climbing fits our bench, not the tournament | Still true. The robustness gate, the finalists as opponents, and the Claude phases (§4, §5) are the answer. |

Spending is capped too: every phase on the API runs under `--budget`.

## 7. Risks

### 7.1 Qwen results don't carry over to Claude

L2 says reasoning effects can even reverse on a stronger model, and Opus 5.5 always thinks. The transfer check (§3 step 4) tells us before the event; the Claude phases at the event (§2.3) catch what it misses. If it fails, the search moves to Claude with a smaller shortlist, at a cost the credits may not cover. The pre-event narrowing then matters even more.

### 7.2 Manipulation

Whether offensive manipulation is allowed is open ([01 §4](01-problem-and-constraints.md#4-what-we-dont-know-and-why-it-matters)). Keep it as a config switch, and arrive with candidates both with and without it.

### 7.3 The home PC

The PC with the 5090 stays at home and is reached remotely all weekend.

- **Access:** Tailscale on the PC and on our laptops. It gives SSH without opening router ports, and works from venue Wi-Fi.
- **The dashboard (port 8000) stays reachable only over Tailscale.** It has no login; never expose it to the internet.
- **Services:** vLLM and the night driver run as systemd services that restart on failure, with a vLLM watchdog that resumes the run (`--resume`). `tmux` for interactive sessions.
- **Power:** sleep and suspend off; the BIOS set to power on after a power loss; Wake-on-LAN.
- **The proposer:** Claude Code in its sandbox (`scripts/claude_proposer.sh`) doesn't need the GPU but uses the subscription allowance all night. Check before the event that the allowance lasts.

A power or internet outage at home ends the run, and nobody can fix it from the venue. The fallback is to run the remaining phases on the API, under a budget cap, from a laptop.

### 7.4 API limits

A low rate tier makes the Claude phases slower than planned (§2.2), and the credits may be smaller than this plan assumes. Ask on Friday; if needed, shrink the Claude re-rank to the top 4, or run it on the screen tier and confirm only the finalists on the full bench.

### 7.5 Requirements we didn't prepare for

If the rules need something no adapter covers (for example multi-issue deals with real trade-offs), Friday's 2–3 hours won't be enough to build it. Then the shortlist is the fallback: pick the candidates least affected, and spend Saturday on the missing piece rather than on tuning.

## 8. What to build

In this order:

| # | Piece | Notes |
|---|---|---|
| 1 | The architectures and their config axes | Through [06](06-agent-contract.md), in separate sessions |
| 2 | Claude model profiles and a pilot | Sonnet 5.5, Opus 5.5, Haiku 4.5; measure tokens per match (§3 step 4.1) |
| 3 | Grid in gym configs | N architectures × M variants listed without writing every challenger by hand |
| 4 | Benches with Claude opponents | 1–2 personas on Claude, for the transfer check and the event |
| 5 | Requirement adapters and bench generator | §3 step 5 |
| 6 | Remote access | §7.3, tested from outside the home network |
| 7 | Night driver | Phases (re-rank → adapt → Claude re-rank or verification → league → report); a time limit and stop conditions; per-phase budget caps; a vLLM watchdog; resume after a crash; a commit after every round on a branch per night |
| 8 | Morning report | One page: every candidate's result on Qwen and Claude, the cut, holdout results, spend, failures, drafted learnings to review |
| 9 | Learnings draft | Code fills in the numbers; an LLM drafts the Learnings sections; both go into an unreviewed section of 05 until a person accepts them |
| 10 | Fresh-seed verification | Re-run chosen agents on a new seed with no cache reuse |
| 11 | Rehearsal | §3 step 8 |

## 9. Open questions

1. How many credits per team, for which models, at which rate tier? Can we get them before the event, for the transfer check?
2. Which Claude model will our tournament agent run on? Latency limits (01 §5, question 3) may decide this before cost does.
3. Which architectures go into the grid, and with which config axes?
