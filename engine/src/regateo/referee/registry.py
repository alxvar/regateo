"""Build deal detectors and message readers from config names."""
from __future__ import annotations

from collections.abc import Callable

from regateo.llm.client import LLMClient
from regateo.referee.detect import DealDetector, LLMJudgeDetector, ShadowDetector, StructuredDetector, TextDetector
from regateo.referee.reader import LLMFirstReader, LLMReader, OfferReader, RuleReader, ShadowReader

JudgeFactory = Callable[[str], LLMClient]   # profile -> client


def build_detector(name: str, judge_llm: JudgeFactory | None = None) -> DealDetector:
    """`structured`, `text`, `llm_judge:<profile>`, or `shadow:<primary>+<shadow>[+...]`
    (the first decides, the rest run in log-only mode)."""
    if name.startswith("shadow:"):
        primary, *shadows = name.removeprefix("shadow:").split("+")
        return ShadowDetector(build_detector(primary, judge_llm), *(build_detector(s, judge_llm) for s in shadows))
    if name == "structured":
        return StructuredDetector()
    if name in ("text", "reading"):
        return TextDetector()
    if name.startswith("llm_judge:"):
        if judge_llm is None:
            raise ValueError("llm_judge needs an LLM factory")
        return LLMJudgeDetector(judge_llm(name.removeprefix("llm_judge:")))
    raise ValueError(f"unknown detector {name!r}")


def build_reader(name: str, llm: JudgeFactory | None = None) -> OfferReader:
    """`rules`, `rules-v2` (stricter about stale and restated prices), `llm:<profile>` (rules, and the model
    for ambiguous messages), `llm-first:<profile>[/<confirm profile>]` (the model reads every message),
    `llm-first-stable:...` (the same, with the transcript tag a hash of the transcript instead of random, so
    re-runs replay from the cache and read the same way), or
    `shadow:<primary>+<shadow>` (the first decides; the second is recorded on each reading)."""
    if name.startswith("shadow:"):
        primary, shadow = name.removeprefix("shadow:").split("+", 1)
        return ShadowReader(build_reader(primary, llm), build_reader(shadow, llm))
    if name == "rules":
        return RuleReader()
    if name == "rules-v2":
        return RuleReader(version=2)
    if name.startswith(("llm-first:", "llm-first-stable:")):
        if llm is None:
            raise ValueError("an llm reader needs an LLM factory")
        stable = name.startswith("llm-first-stable:")
        first, _, confirm = name.split(":", 1)[1].partition("/")
        return LLMFirstReader(llm(first), confirm=llm(confirm) if confirm else None, stable_tag=stable)
    if name.startswith("llm:"):
        if llm is None:
            raise ValueError("an llm reader needs an LLM factory")
        return LLMReader(llm(name.removeprefix("llm:")))
    raise ValueError(f"unknown reader {name!r}")
