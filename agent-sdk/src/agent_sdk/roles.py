"""Buyer and seller roles, and u-space: one numeric code path for both roles."""
from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    BUYER = "buyer"
    SELLER = "seller"


def other(role: Role) -> Role:
    return Role.BUYER if role is Role.SELLER else Role.SELLER


def sign(role: Role) -> int:
    """+1 for a seller (higher price is better), -1 for a buyer (lower price is better).

    Multiplying a price by `sign(role)` gives that role's utility ("u-space"), so
    comparisons like "is this offer better for us" are written once for both roles.
    """
    return 1 if role is Role.SELLER else -1


def better_or_equal(role: Role, a: float, b: float) -> bool:
    """True when price `a` is at least as good as price `b` for `role`."""
    return sign(role) * a >= sign(role) * b
