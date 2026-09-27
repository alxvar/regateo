"""Statistics over outcomes: confidence intervals, paired tests, Bradley-Terry ratings."""
from regateo.stats.paired import PairedResult, paired_test
from regateo.stats.ratings import bradley_terry, match_score
from regateo.stats.summary import Estimate, mean_ci, wilson

__all__ = ["Estimate", "PairedResult", "bradley_terry", "match_score", "mean_ci", "paired_test", "wilson"]
