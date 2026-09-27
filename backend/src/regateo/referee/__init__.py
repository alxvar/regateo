"""Text-based deal detection and scoring (surplus share)."""
from regateo.referee.detect import (
    DealDetector,
    DealEvent,
    LLMJudgeDetector,
    ShadowDetector,
    StructuredDetector,
    TextDetector,
)
from regateo.referee.prices import PriceMention, find_prices, stated_prices
from regateo.referee.registry import build_detector
from regateo.referee.scoring import score

__all__ = [
    "DealDetector", "DealEvent", "build_detector", "LLMJudgeDetector", "PriceMention", "ShadowDetector",
    "StructuredDetector", "TextDetector", "find_prices", "score", "stated_prices",
]
