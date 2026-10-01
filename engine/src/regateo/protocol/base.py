"""The platform contract: who moves first, what gets delivered, what each side can see.

The real platform's rules are unknown (docs/01 §5). Everything that depends on them goes
through a TurnProtocol, so answering those questions means adding or tuning one class.
"""
from __future__ import annotations

import random
from abc import ABC, abstractmethod

from agent_sdk.context import ProtocolInfo

from regateo.core.messages import Message, Move
from regateo.core.roles import Role
from regateo.core.scenario import FirstMover, Rules, Scenario


class TurnProtocol(ABC):
    name: str
    structured: bool      # True: the platform carries action/price fields next to the text

    def first_mover(self, scenario: Scenario, rng: random.Random) -> Role:
        match scenario.rules.first_mover:
            case FirstMover.SELLER:
                return Role.SELLER
            case FirstMover.BUYER:
                return Role.BUYER
            case _:
                return rng.choice([Role.SELLER, Role.BUYER])

    def normalise(self, move: Move, rules: Rules) -> Move:
        """The move as the platform would accept it: text capped, unsupported fields dropped.
        Agent metadata stays; it is recorded but never delivered."""
        text = move.text.strip()[: rules.max_message_chars]
        if self.structured:
            return move.model_copy(update={"text": text})
        meta = move.meta
        if move.action is not None or move.price is not None:
            # Kept as ground truth for auditing how the referee reads the text.
            meta = {**meta, "intent": {"action": move.action, "price": move.price}}
        return move.model_copy(update={"text": text, "action": None, "price": None, "meta": meta})

    def delivered(self, move: Move) -> Move:
        """What the other side receives: no agent metadata, structured fields only if supported."""
        if self.structured:
            return Move(text=move.text, action=move.action, price=move.price)
        return Move(text=move.text)

    def view_of(self, history: list[Message], viewer: Role) -> list[Message]:
        """History as `viewer` may see it: their own messages in full, the opponent's as delivered.
        The referee's readings are hidden from both, as a real platform would not provide them."""
        return [m.model_copy(update={"reading": None}) if m.sender is viewer
                else m.model_copy(update={"move": self.delivered(m.move), "reading": None})
                for m in history]

    def info(self) -> ProtocolInfo:
        """What agents are told about this protocol."""
        return ProtocolInfo(name=self.name, structured=self.structured, description=self.describe())

    @abstractmethod
    def describe(self) -> str:
        """One line for agent prompts: how offers and acceptances work on this platform."""
