"""Janus — measure a routing policy on your data, then run it.

Janus never assumes which model is better. It measures a policy on the
customer's own data and then executes it.

That is not a stylistic preference. The experiment in `experiments/`, published
with its raw data, ran the identical pipeline on two labelled datasets and found
that none of the routing parameters carried over: the optimal threshold moved
from 0.67 to 0.37, the sign of the accuracy gap between the two models reversed,
the saturated confidence level halved in size, and routing went from gaining
accuracy on one dataset to gaining nothing for more money on the other.

So this package ships no default threshold, and `Router` refuses to run without
a measured policy.

    from janus import Router

    router = Router.from_file("janus.json", primary=..., fallback=...)
    decision = router.decide(input="I lost my card", question=question)
"""

from .labels import from_json as question_from_json
from .labels import from_module as question_from_module
from .measure import BudgetExceeded, measure
from .policy import (InvalidPolicyError, NoPolicyError, Policy, PolicyError,
                     StalePolicyError)
from .providers.base import Provider, prompt_hash
from .providers.registry import register, resolve
from .router import Router
from .types import (Answer, CalibrationReport, Decision, LevelRow, Measurement,
                    OperatingPoint, Question)

__version__ = "0.3.1"

__all__ = [
    "Router", "measure", "Policy", "Question",
    "Answer", "Decision", "Measurement", "LevelRow", "OperatingPoint",
    "CalibrationReport", "Provider", "resolve", "register", "prompt_hash",
    "question_from_json", "question_from_module",
    "PolicyError", "NoPolicyError", "InvalidPolicyError", "StalePolicyError",
    "BudgetExceeded", "__version__",
]
