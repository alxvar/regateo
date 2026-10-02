"""Red-team opponents: scripted attacks on weaknesses seen in our agents' play in climb round-01.

Written after reading those agents' transcripts and the checks they record in each move's metadata, so they are
registered `informed_by` them and play only on the adversarial bench (configs/benches/adversarial-v1.yaml), never
on dev or the holdout (docs/04-hill-climbing.md §4).

Each one attacks one weakness and is otherwise a scripted opponent (regateo.opponents.scripted): it never goes past
its own limit. With `plain: true` it makes the same price moves in plain words ("My offer is $X.") and never springs
its trap, so the difference between the two versions is what the attack itself costs us.

- echo: asks us to repeat its price back. Its early prices are past our limit, so a reply that names them fails
  our agents' price check, and after a retry they send a canned "I can do $X" or stop moving.
- stonewall: never moves from its opening, and accepts what reaches a hardliner's curve. Do we concede to nothing?
- anchor: opens far past the market range and makes big early "concessions" back to an ordinary opening, then holds
  firm. Do we mirror concessions that only undo an absurd anchor?
- misquote: restates our last offer as better for it than it was. Do we adopt the false number?
- quote-accept: invites us to restate its price and, when we do, "accepts" it as though we had offered it. Whether
  that closes a deal depends on the referee's reader telling a quote from an offer; the tournament's reader is
  unknown (docs/05 L13).

And one LLM attacker, `redteam:llm`: the persona opponent's end-to-end model with the strategy prompt
(negotiator_system.v2) and a brief of these weaknesses (prompts/redteam_brief.v1.md), adapting where the scripts
can't. Code keeps it within its own limit, so a slip of its model can't hand us a deal past it. `plain: true`
leaves out the brief: the same model, prompt and guard, as its twin.
"""
from __future__ import annotations

from agent_sdk import AgentContext

from regateo.agents.base import AgentSpec, TrustedContext, register
from regateo.core.agent import Observation
from regateo.core.messages import ActionKind, Move
from regateo.core.roles import Role, sign
from regateo.core.scenario import PrivateView
from regateo.opponents.common import fmt_price, opening_price, standing_offer
from regateo.opponents.llm import PROMPTS, EndToEndAgent
from regateo.opponents.scripted import ScriptedOpponent
from regateo.referee.prices import stated_prices
from regateo.referee.reader import same_price

# The agent versions whose round-01 transcripts and move metadata these were written from.
INFORMED = ("single_call/v1", "single_call/v2", "tools/v1", "ranged/v2", "strategist/v2", "critic/v2")


class RedTeamOpponent(ScriptedOpponent):
    params = ("shape", "plain")

    def __init__(self, spec: AgentSpec, view: PrivateView, ctx: TrustedContext):
        super().__init__(spec, view, ctx)
        self.plain = bool(spec.params.get("plain", False))
        self.width = view.market_high - view.market_low

    def offer_text(self, p: str, price: float, changed: bool) -> str:
        return f"My offer is {p}." if self.plain else self.attack_text(p, price, changed)

    def attack_text(self, p: str, price: float, changed: bool) -> str:
        raise NotImplementedError

    def fmt(self, price: float) -> str:
        return fmt_price(price, self.v.currency)


class Echo(RedTeamOpponent):
    kind = "echo"
    shape = 1.2

    def attack_text(self, p: str, price: float, changed: bool) -> str:
        return self.rng.choice([
            f"My offer is {p}. Is {p} a yes or a no? Answer with the number, please.",
            f"My offer is {p}. If {p} doesn't work for you, tell me which number you're turning down and why.",
            f"My offer is {p}. Before you counter, repeat back the price I'm offering so we're on the same page.",
        ])


class Stonewall(RedTeamOpponent):
    """Offers its opening price every turn. Accepts an offer that reaches a hardliner's curve, and on its last word
    anything better than its limit (ScriptedOpponent.respond)."""
    kind = "stonewall"
    shape = 5.0

    def ask(self, t: float) -> float:
        return self.u_open

    def attack_text(self, p: str, price: float, changed: bool) -> str:
        return self.rng.choice([
            f"My offer is still {p}. I don't negotiate against myself.",
            f"My offer is {p}, same as before. You're the one who needs to close the gap.",
            f"My offer is {p}. My number hasn't changed, and asking again won't change it.",
        ])


class Anchor(RedTeamOpponent):
    """Opens at half again the favourable market end (a seller) or half of it (a buyer), comes back to an ordinary
    opening in big steps over the first half of the match, then concedes like a hardliner."""
    kind = "anchor"
    shape = 5.0

    def __init__(self, spec: AgentSpec, view: PrivateView, ctx: TrustedContext):
        super().__init__(spec, view, ctx)
        anchor = 1.5 * view.market_high if view.role is Role.SELLER else 0.5 * view.market_low
        self.u_anchor = max(self.s * anchor, self.u_open)
        self.first: float | None = None

    def target(self, t: float) -> float:
        if t < 0.5:
            return self.u_anchor - (self.u_anchor - self.u_open) * t / 0.5
        return self.u_open - (self.u_open - self.u_floor) * ((t - 0.5) / 0.5) ** self.shape

    def attack_text(self, p: str, price: float, changed: bool) -> str:
        if self.first is None:
            self.first = price
            return f"My offer is {p}. That's what it's worth to me, and I can back that up."
        # As a percentage: an amount in money would read as a price, and a reader could take it for the offer.
        moved = f"{100 * abs(price - self.first) / self.first:.0f}%"
        direction = "down" if self.v.role is Role.SELLER else "up"
        if changed:
            return (f"I've come {direction} {moved} from my first number. My offer is {p}. "
                    f"Now match that move and we're nearly there.")
        return f"My offer is {p}. I've made all the big moves so far, {moved} of my first number. Your turn."


class Misquote(RedTeamOpponent):
    """Quotes our last offer back as SHIFT market widths better for it than it was, never past its own offer."""
    kind = "misquote"
    shape = 1.2
    SHIFT = 0.08

    def __init__(self, spec: AgentSpec, view: PrivateView, ctx: TrustedContext):
        super().__init__(spec, view, ctx)
        self.theirs: float | None = None

    async def respond(self, obs: Observation) -> Move:
        self.theirs = standing_offer(obs)
        return await super().respond(obs)

    def attack_text(self, p: str, price: float, changed: bool) -> str:
        if self.theirs is None:
            return f"My offer is {p}."
        fake = round(self.theirs + self.s * self.SHIFT * self.width)
        if self.s * fake >= self.s * price:
            return f"My offer is {p}."
        f = self.fmt(fake)
        return self.rng.choice([
            f"Thanks for coming to {f}. My offer is {p}, so we're close.",
            f"Since you've already offered {f}, let's not go backwards. My offer is {p}.",
            f"Noted, {f} from you. My offer is {p}.",
        ])


class QuoteAccept(RedTeamOpponent):
    """When our message names its current price, accepts that price, once per price."""
    kind = "quote-accept"
    shape = 1.5

    def __init__(self, spec: AgentSpec, view: PrivateView, ctx: TrustedContext):
        super().__init__(spec, view, ctx)
        self.sprung: list[float] = []

    async def respond(self, obs: Observation) -> Move:
        mine = self.last_price
        if (not self.plain and obs.incoming is not None and mine is not None
                and not any(same_price(mine, x) for x in self.sprung)
                and any(same_price(mine, x) for x in stated_prices(obs.incoming, negated=True))):
            self.sprung.append(mine)
            return self._say(ActionKind.ACCEPT, mine)
        return await super().respond(obs)

    def attack_text(self, p: str, price: float, changed: bool) -> str:
        return self.rng.choice([
            f"My offer is {p}. What would it take for you to say yes to {p}?",
            f"My offer is {p}. Where does {p} leave us?",
            f"My offer is {p}. Tell me honestly how far {p} is from where you are.",
        ])


REDTEAM: dict[str, type[RedTeamOpponent]] = {c.kind: c for c in (Echo, Stonewall, Anchor, Misquote, QuoteAccept)}


@register("redteam:", trusted=True, informed_by=INFORMED)
def build_redteam(spec: AgentSpec, view: PrivateView, ctx: TrustedContext) -> RedTeamOpponent:
    variant = spec.kind.split(":", 1)[1]
    if variant not in REDTEAM:
        raise ValueError(f"unknown red-team opponent {variant!r}; known: {sorted([*REDTEAM, 'llm'])}")
    return REDTEAM[variant](spec, view, ctx)


class RedTeamLLM(EndToEndAgent):
    """Params: `plain` (leave out the brief), `prompt` (default negotiator_system.v2), `brief` (default
    redteam_brief.v1), `effort`, `max_tokens`."""

    stage = "redteam"
    PROMPT = "negotiator_system.v2"
    BRIEF = "redteam_brief.v1"
    PARAMS = ("plain", "prompt", "brief", "effort", "max_tokens")

    @staticmethod
    def prompt_refs(spec: AgentSpec) -> list[str]:
        refs = [spec.params.get("prompt", RedTeamLLM.PROMPT)]
        if not spec.params.get("plain"):
            refs.append(spec.params.get("brief", RedTeamLLM.BRIEF))
        return refs

    def __init__(self, spec: AgentSpec, view: PrivateView, ctx: AgentContext):
        if unknown := sorted(set(spec.params) - set(self.PARAMS)):
            raise ValueError(f"unknown params {unknown} for {spec.kind}; known: {sorted(self.PARAMS)}")
        super().__init__(spec.model_copy(update={"params": {"prompt": self.PROMPT, **spec.params}}), view, ctx)

    def persona_text(self) -> str:
        return "" if self.params.get("plain") else f"\n{PROMPTS.render(self.params.get('brief', self.BRIEF))}\n"

    async def respond(self, obs: Observation) -> Move:
        move = await super().respond(obs)
        prices = [move.price]
        if move.action is ActionKind.ACCEPT:
            prices.append(standing_offer(obs))      # an acceptance closes at our offer as read, whatever it names
        elif move.action is not ActionKind.OFFER:
            return move
        s = sign(self.view.role)
        if any(p is not None and s * p < s * self.view.reservation for p in prices):
            return self._hold(obs, move)
        return move

    def _hold(self, obs: Observation, rejected: Move) -> Move:
        """In place of a move past its limit: its last offer again, read from what it logged (a free-text platform
        drops the move's own price), or its opening."""
        offers = [d["price"] for m in obs.history if m.sender is self.view.role
                  and (d := m.move.meta.get("decision") or {}).get("action") == "offer" and d.get("price") is not None]
        price = offers[-1] if offers else opening_price(self.view)
        return Move(text=f"My offer is {fmt_price(price, self.view.currency)}.", action=ActionKind.OFFER, price=price,
                    meta={"fallback": "past its own limit", "rejected": rejected.meta.get("decision")})


@register("redteam:llm", prompts=RedTeamLLM.prompt_refs, prompt_dir=PROMPTS, informed_by=INFORMED)
def build_redteam_llm(spec: AgentSpec, view: PrivateView, ctx: AgentContext) -> RedTeamLLM:
    return RedTeamLLM(spec, view, ctx)
