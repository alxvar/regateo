"""Bradley-Terry ratings from pairwise results, on an Elo-like scale."""
from __future__ import annotations

import math
from collections import defaultdict

PRIOR_GAMES = 1.0     # each pair gets one virtual drawn game: keeps ratings finite for unbeaten agents


def bradley_terry(results: list[tuple[str, str, float]], *, iters: int = 2000, tol: float = 1e-10) -> dict[str, float]:
    """`results`: (a, b, score of a) with score 1 = a won, 0 = b won, 0.5 = draw.

    Fitted with the MM algorithm (Hunter 2004). Returned as 1500 + 400*log10(strength),
    so a 400-point gap means 10:1 odds, as in Elo.
    """
    players = sorted({p for a, b, _ in results for p in (a, b)})
    if not players:
        return {}
    wins: dict[str, float] = defaultdict(float)
    games: dict[tuple[str, str], float] = defaultdict(float)
    for a, b, s in results:
        wins[a] += s
        wins[b] += 1 - s
        games[(a, b)] += 1
        games[(b, a)] += 1
    for a, b in list(games):
        if a < b:
            for x, y in ((a, b), (b, a)):
                games[(x, y)] += PRIOR_GAMES
                wins[x] += PRIOR_GAMES / 2
    strength = dict.fromkeys(players, 1.0)
    for _ in range(iters):
        new = {}
        for i in players:
            denom = sum(n / (strength[i] + strength[j]) for (x, j), n in games.items() if x == i)
            new[i] = wins[i] / denom if denom else strength[i]
        g = math.exp(sum(math.log(v) for v in new.values()) / len(new))
        new = {k: v / g for k, v in new.items()}
        delta = max(abs(new[k] - strength[k]) for k in players)
        strength = new
        if delta < tol:
            break
    return {p: 1500 + 400 * math.log10(strength[p]) for p in players}


def match_score(share_a: float, share_b: float, deal: bool) -> float:
    """Pairwise result for rating: whoever captured more surplus wins; no deal is a draw."""
    if not deal or abs(share_a - share_b) < 1e-9:
        return 0.5
    return 1.0 if share_a > share_b else 0.0
