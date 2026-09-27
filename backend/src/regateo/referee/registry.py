"""Build deal detectors from config names."""
from __future__ import annotations

from collections.abc import Callable

from regateo.llm.client import LLMClient
from regateo.referee.detect import DealDetector, LLMJudgeDetector, ShadowDetector, StructuredDetector, TextDetector

JudgeFactory = Callable[[str], LLMClient]   # profile -> client


def build_detector(name: str, judge_llm: JudgeFactory | None = None) -> DealDetector:
    """`structured`, `text`, `llm_judge:<profile>`, or `shadow:<primary>+<shadow>[+...]`
    (the first decides, the rest run in log-only mode)."""
    if name.startswith("shadow:"):
        primary, *shadows = name.removeprefix("shadow:").split("+")
        return ShadowDetector(build_detector(primary, judge_llm), *(build_detector(s, judge_llm) for s in shadows))
    if name == "structured":
        return StructuredDetector()
    if name == "text":
        return TextDetector()
    if name.startswith("llm_judge:"):
        if judge_llm is None:
            raise ValueError("llm_judge needs an LLM factory")
        return LLMJudgeDetector(judge_llm(name.removeprefix("llm_judge:")))
    raise ValueError(f"unknown detector {name!r}")
