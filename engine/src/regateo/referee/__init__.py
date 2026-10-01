"""Reading messages, deal detection and scoring (surplus share)."""
from regateo.referee.detect import (
    DealDetector,
    DealEvent,
    LLMJudgeDetector,
    ShadowDetector,
    StructuredDetector,
    TextDetector,
)
from regateo.referee.prices import PriceMention, find_prices, stated_prices
from regateo.referee.reader import LLMReader, OfferReader, RuleReader, ShadowReader, with_readings
from regateo.referee.registry import build_detector, build_reader
from regateo.referee.scoring import score

__all__ = [
    "DealDetector", "DealEvent", "LLMJudgeDetector", "LLMReader", "OfferReader", "PriceMention", "RuleReader",
    "ShadowDetector", "ShadowReader", "StructuredDetector", "TextDetector", "build_detector", "build_reader",
    "find_prices", "score", "stated_prices", "with_readings",
]
