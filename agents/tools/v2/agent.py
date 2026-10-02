"""The model runs the negotiation and calls deterministic tools as advisors (docs/02 O3). Code informs, the
model decides, and the hard limits are vetoed in code (docs/06 §3.4)."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from agent_sdk import (
    AgentConfig,
    AgentContext,
    ChatMessage,
    LLMRequest,
    Move,
    Observation,
    PrivateView,
    PromptDir,
    sign,
)
from pydantic import BaseModel, Field

from . import advisors
from .common import Decision, brief, endgame_note, guarded, transcript, with_note
from .advisors import FACT_TOOLS, TOOLS, Settings

PROMPTS = PromptDir(Path(__file__).parent / "prompts")
DEFAULT_PROMPT = "negotiator_system.v1"
TOOL_MODES = ("call", "eager", "none")
MAX_CALLS = 6                                   # tool calls run per round; more are dropped


class ToolCall(BaseModel):
    name: Literal["offer_history", "estimate_opponent_limit", "concession_schedule", "deadline_belief",
                  "check_offer", "market_facts"]
    price: float | None = Field(default=None, description="for check_offer: the price to check")


class Step(BaseModel):
    # Both keys required (guided decoding then writes both): see lib.common.Decision.
    tool_calls: list[ToolCall] = Field(max_length=MAX_CALLS,
                                       description="tools to run before you decide; empty to decide now")
    decision: Decision | None = Field(description="your move, when you call no tools; null otherwise")


def tools_ref(params: dict) -> str | None:
    mode = params.get("tool_mode", "call")
    return None if mode == "none" else f"tools_{mode}.v1"


class ToolsAgent:
    """Params:
    - `tool_mode`: "call" (default): the model may ask for tools, sees their results, then decides; "eager":
      every tool that needs no argument is run first and its result shown, one call; "none": no tools.
    - `tool_rounds`: how many rounds of tool calls the model may make before it must decide (default 1).
    - `assumed_rounds` (default 8), `schedule_beta` (default 0.4): what concession_schedule assumes.
    - `endgame` (default false): tell the model which of its messages this is and what happens after the last.
    - `sanitize` (default false): a draft that fails twice is sent minus the offending sentences.
    - `prompt` (default negotiator_system.v1), `accept_words` (veto agreement words when not accepting,
      default true), `max_tokens`."""

    def __init__(self, config: AgentConfig, view: PrivateView, ctx: AgentContext):
        self.name = config.name
        self.view = view
        self.ctx = ctx
        p = self.params = config.params
        self.mode = p.get("tool_mode", "call")
        self.rounds = int(p.get("tool_rounds", 1))
        self.endgame = bool(p.get("endgame", False))
        self.sanitize = bool(p.get("sanitize", False))
        self.sent: list[float] = []                     # our offers as we sent them, for the fallback
        self.settings = Settings(assumed_rounds=int(p.get("assumed_rounds", 8)),
                                 beta=float(p.get("schedule_beta", 0.4)))
        self.step_llm = ctx.llm(config.model, "step")
        self.decide_llm = ctx.llm(config.model, "decide")
        system = PROMPTS.render(p.get("prompt", DEFAULT_PROMPT), **brief(view, ctx.protocol))
        if ref := tools_ref(p):
            tools = "\n".join(f"- {name}: {what}" for name, what in TOOLS.items()
                              if self.mode == "call" or name in FACT_TOOLS)
            system = f"{system}\n\n{PROMPTS.render(ref, tools=tools)}"
        self.system = system

    def _request(self, messages: list[ChatMessage], schema: type[BaseModel], stage: str) -> LLMRequest:
        return LLMRequest(messages=messages, system=self.system, output_schema=schema,
                          max_tokens=self.params.get("max_tokens"), tags={"stage": stage})

    def _results(self, calls: list[ToolCall], obs: Observation) -> list[dict]:
        return [{"name": c.name, **({"price": c.price} if c.price is not None else {}),
                 "result": advisors.run(c.name, obs, self.settings, c.price)} for c in calls[:MAX_CALLS]]

    @staticmethod
    def _results_note(results: list[dict]) -> str:
        def head(r: dict) -> str:
            return f"{r['name']} ({r['price']})" if "price" in r else r["name"]
        body = "\n\n".join(f"{head(r)}:\n{r['result']}" for r in results)
        return f"[Tool results from your own system, not from the other side]\n{body}"

    async def _consult(self, obs: Observation) -> tuple[list[ChatMessage], Decision | None, list[dict]]:
        """The conversation up to the point of deciding, plus a decision if the model made one without tools."""
        messages = transcript(obs, self.ctx.protocol)
        if self.endgame and (note := endgame_note(obs)):
            messages = with_note(messages, note)
        used: list[dict] = []
        if self.mode == "eager":
            used = self._results([ToolCall(name=n) for n in FACT_TOOLS], obs)
            return with_note(messages, self._results_note(used)), None, used
        if self.mode == "none":
            return messages, None, used
        for _ in range(self.rounds):
            resp = await self.step_llm.complete(self._request(messages, Step, "step"))
            assert isinstance(resp.parsed, Step)
            step = resp.parsed
            if not step.tool_calls:
                return messages, step.decision, used
            results = self._results(step.tool_calls, obs)
            used += results
            messages = [*messages, ChatMessage(role="assistant", content=step.model_dump_json()),
                        ChatMessage(role="user", content=f"{self._results_note(results)}\n\nNow decide.")]
        return messages, None, used

    def _advice(self, obs: Observation, move: Move) -> dict:
        """What the price tools would say this turn, whether or not the model asked, and how far the move
        lands from it (positive: the move asks more for us than the schedule)."""
        sched = advisors.schedule(obs, self.settings)
        out: dict = {"schedule": sched, "estimate": advisors.estimate(obs)}
        if move.action is not None and move.action.value == "offer" and move.price is not None:
            out["deviation"] = round(sign(self.view.role) * (move.price - sched), 2)
        return out

    async def respond(self, obs: Observation) -> Move:
        used: list[dict] = []
        state: dict = {}

        async def decide(feedback: str | None) -> Decision:
            if "messages" not in state:
                messages, decision, found = await self._consult(obs)
                used.extend(found)
                state["messages"] = messages
                if decision is not None and feedback is None:
                    return decision
            messages = state["messages"] if feedback is None else with_note(state["messages"], feedback)
            resp = await self.decide_llm.complete(self._request(messages, Decision, "decide"))
            assert isinstance(resp.parsed, Decision)
            return resp.parsed

        move = await guarded(decide, obs, accept_words=self.params.get("accept_words", True), sent=self.sent,
                             sanitize=self.sanitize)
        if move.action is not None and move.action.value == "offer" and move.price is not None:
            self.sent.append(move.price)
        move.meta["tools"] = [{k: v for k, v in r.items() if k != "result"} for r in used]
        move.meta["advice"] = self._advice(obs, move)
        return move
