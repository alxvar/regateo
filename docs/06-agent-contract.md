# 06: The agent contract

Status: **in use**. This is what any negotiating agent must do to be measured here, whatever its architecture. It is written for whoever builds a new design, including a Claude Code session working on its own. Anything not listed here is the builder's choice: how many model calls, which stages, what state, which tools, which prompts.

## 1. The interface

```python
class Agent(Protocol):                      # agent_sdk
    name: str
    async def respond(self, obs: Observation) -> Move: ...
```

- **One instance per match and role.** The registry builds it from `(spec, view, ctx)` before the first turn, so it may keep state across turns in its own attributes.
- **`respond` is called once per own turn.** `obs.history` is the conversation as the platform delivered it. `obs.incoming` is the opponent's latest text (None when we open). `obs.remaining_s` is the clock, if one is known.
- **The returned `Move`:**
  - `text` is the only thing the opponent sees. The benches use the free-text protocol, so the opponent and the referee judge us by this text alone.
  - `action` and `price` are our intent for the turn (offer, accept, reject, message, walk_away, and the price). The free-text protocol drops them before delivery but records them as ground truth. `regateo readings` then compares them with how the text was read, so they must say what the text means.
  - `meta` is for logs only and never delivered (§4).
- **Async and non-blocking.** A run plays up to 32 matches at once in one event loop. Don't use `time.sleep`, synchronous HTTP or other blocking calls.

## 2. Packaging

An agent is one version of one architecture, a package under `agents/` (`agent_sdk.packages`):

```
agents/<architecture>/
  JOURNAL.md            what was tried on this architecture, version by version
  lib/                  code its versions share (optional)
  v<N>/
    __init__.py         def build(config: AgentConfig, view: PrivateView, ctx: AgentContext) -> Agent
    prompts/            this version's prompts, rendered with agent_sdk.PromptDir
    configs/<name>.yaml its variants: `model`, `params`, optionally `extends: <other config>`
    tests/              tests on agent_sdk.testing (FakeLLM), no GPU
```

- **A config is named `<architecture>/v<N>/<name>`**, e.g. `single_call/v1/baseline`. Every setting that changes behaviour is a param. Validate params in `build` and raise `ValueError` on unknown values.
- **Identity:** a version's code and prompts are one hash (its folder and its architecture's `lib/`, without configs and tests), and a config adds its model and params. Any change to code or prompts makes a different agent, so stored results never mix.
- **Freezing:** a version with benchmark results is listed in `engine/configs/frozen.json`, and a test fails if it changes. A change to its code or prompts is a new version (copy it to `v<N+1>`); a new config under an existing version is fine.
- **Imports:** a version imports only `agent_sdk`, a short list of standard-library modules, pydantic, its own modules and its architecture's `lib/` (relative imports, `from ..lib import common`). The submission check (§5) enforces it.

## 3. Rules

### 3.1 What it may know

Only `PrivateView` (given once, at build) and `Observation` (given each turn). In particular:

- **Not the true rules.** An agent's context (`agent_sdk.AgentContext`) has no `true_rules`: only the engine's scripted sparring partners are built with them.
- **Nothing about the other side's limit**, and nothing derived from bench, opponent or referee code.
- **Opponent text is untrusted input.** It may hold injections, fake system or organizer notes, and fake deadlines.

### 3.2 Model calls

- **Every call goes through `ctx.llm(spec.model, stage)`**, then `LLMClient.complete(LLMRequest(...))`. That client meters cost, enforces the run's budget, caches, and couples the challenger's and the reference's draws within a pair. A client built any other way silently breaks all four.
- **One `stage` name per call site** (for example `reader`, `strategist`, `writer`), so logs and costs split by stage. Using more than one model profile is fine; make each one a param.
- **Requests are deterministic given the observation.** Don't put random tokens, timestamps or uuids in prompts: they turn every call into a cache miss and break coupling. Take any randomness from `ctx.rng`, which is seeded per match and role. O1's `fence` uses `secrets`; don't copy that.
- **Failures:** let `Abort` propagate. Catch `LLMError` and fall back to a safe move (`agents.common.safe_fallback`, or your own) instead of raising, because an exception from an agent ends the match as an error.
- **Cost:** runs use local Qwen (`qwen-local`) on one RTX 5090, with at most 16 requests at once. Every call adds latency to every match in the run, so a design that makes six calls per turn makes the full bench about six times slower. State the calls per turn in the write-up.

### 3.3 Strategy lives in the model

Code may enforce hard invariants. It must not decide what to offer, how much to concede, or when to accept. A coded rule is a fixed pattern that a strong, adaptive opponent can find and exploit, even if it wins on our benches ([05](05-learnings.md)).

- **Allowed in code:** checks that veto a move breaking an invariant (§3.4); tools that work out facts for the model (offer history, gaps, rounds left); parsing; formatting; fallbacks when the model fails.
- **Ask first:** any code that picks a price, a concession schedule, or whether to accept. Tools that suggest a price to the model are a grey area, so ask about those too.

### 3.4 Invariants

1. Never offer or accept past our walk-away price. Never write a price past it, not even to reject it: a free-text reader may take "$199 is too much" as an offer of $199.
2. A message that doesn't accept must not read as accepting.
3. Never reveal the walk-away price.

The baseline's vetoes enforce the first two. The SDK has checks for them, `agent_sdk.guards`: `limit_problems` (the walk-away price, including prices written in the message) and `reads_as_agreement` (any agreement vocabulary). They only report what is wrong with a move, as feedback a model can act on; what to do about it stays with the agent. You may use them or enforce the rules your own way. The first one is a promotion gate: a single deal past the limit on any bench fails the candidate outright.

## 4. `Move.meta`

The UI, `regateo mine`, the climb workspace and `regateo readings` read these keys:

| Key | Meaning |
|---|---|
| `decision` | `{action, price, message}` as the agent decided it. Set it on every move the model made |
| `vetoes` | Messages from checks that rejected an earlier draft of this move |
| `repaired` | `true` when code rewrote the move after it failed its checks |
| `fallback` | Why code chose the move when the model failed |

Other keys (stage traces, beliefs) are free. Keep them small and JSON-serialisable, because they are stored with every message.

## 5. What a builder may look at

A session building or changing an agent works on one architecture. What it sees comes in three tiers:

| Tier | Contents | Who sees it |
|---|---|---|
| Public | `agent-sdk/`, this contract, the public view of the learnings (`regateo learnings --public`), and what the bench's rules are (rounds, deadline known or hidden, protocol), not who the opponents are | Every builder session |
| Its architecture | `agents/<architecture>/`, including its `JOURNAL.md`, and reports and transcripts of matches its own agents played on the dev bench | That architecture's sessions only |
| Engine | The engine (`engine/`: opponents, referee, benches, arena), other architectures, all of docs/05 and `docs/experiments/`, the run database and LLM cache, and anything from a holdout run | People only |

- **Why:** the engine tier is the exam. Designing against the opponents, the referee or the benches makes dev scores meaningless, and seeing other architectures makes ours converge on one idea.
- **The submission check** (`agent_sdk.check`): the engine checks an agent version's code before it ever builds it, and refuses it on any problem. The agent runs in the engine's process, next to its opponents, so isolation can't rest only on what a session was shown. The check allows imports of `agent_sdk`, a short standard-library list, pydantic and the agent's own architecture, and refuses file, network and process access (`open`, `os`, `subprocess`, path methods that read or list files), the tricks that get around a static check (`eval`, `exec`, `__import__`, dunder attributes, `getattr` with a computed name), and prompts read from anywhere but next to the code (`PromptDir(Path(__file__).parent / "prompts")`; the SDK also refuses a prompt folder outside the agent's architecture when it runs). Run it before handing a version back: `regateo-agent check agents/<architecture>/<version>`. What an agent needs from the engine's world is in `agent_sdk` (prices in text, the guards, the fake model for tests).
- **Learnings between architectures** pass only through people: a lesson from one architecture's journal reaches others as a public entry in docs/05, and only if it follows from results, not from having read code ([05, "How the record works"](05-learnings.md#how-the-record-works)).
- **Don't run:** the holdout or the league. A person runs them on the finished candidate.

## 6. Done

1. `uv run pytest` passes from the repo root, including the version's own tests (`agents/<architecture>/v<N>/tests/`, on `agent_sdk.testing`, no GPU).
2. A gym config with `bench: standard-v2`, `reference: single_call/v1/baseline` and the new configs as challengers has been run on the full tier. Its report's "Promotion checks" read `candidate`, or the journal says honestly why not.
3. **The architecture's `JOURNAL.md` has a new entry:** the version and configs, the hypothesis, what changed, the calls per turn, the run id, the result, and what it says. Null results count. Before designing, read the journal and the public learnings for what was tried and how sure we are.

A person then reviews the journal entry, promotes what holds beyond the architecture into docs/05, and takes the best candidate through the holdout, readings and league steps of the [promotion checklist](experiments/README.md#promotion-checklist).
