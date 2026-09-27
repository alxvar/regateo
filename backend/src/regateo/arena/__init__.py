"""Tournaments across a roster of agents: round robin, ratings, leaderboard."""
from regateo.arena.report import ArenaReport, build_arena_report
from regateo.arena.run import run_arena
from regateo.arena.spec import ArenaSpec

__all__ = ["ArenaReport", "ArenaSpec", "build_arena_report", "run_arena"]
