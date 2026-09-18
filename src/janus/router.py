"""Le routeur : execute une politique mesuree, et rien d'autre.

Janus ne suppose jamais quel modele est le meilleur. Il execute la politique que
`janus measure` a produite sur les donnees du client. Trois consequences
directes, toutes tirees de la mesure :

- **Aucun seuil par defaut.** Sans politique, `Router` leve `NoPolicyError`.
  Les deux datasets mesures ont donne 0,67 et 0,37 : aucune de ces valeurs n'a
  de sens ailleurs, donc aucune n'est cablee.
- **`always_fallback` n'interroge pas le primary.** Quand la politique dit de
  toujours escalader, payer le primary pour une confiance dont personne ne se
  sert serait une perte seche.
- **La derive de modele arrete le routeur par defaut.** L'alias bouge, la mesure
  ne suit pas. `on_drift="warn"` ou `"ignore"` pour en decider autrement.
"""

from __future__ import annotations

import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Sequence

from .metrics import round_confidence
from .policy import NoPolicyError, Policy, StalePolicyError
from .providers.base import Provider
from .types import Answer, Decision, Question

OnDrift = Literal["raise", "warn", "ignore"]


class Router:
    """Execute une politique. Synchrone."""

    def __init__(self, policy: Policy, *, primary: Provider,
                 fallback: Provider | None = None,
                 on_drift: OnDrift = "raise") -> None:
        policy.validate()
        if policy.rule != "always_primary" and fallback is None:
            raise ValueError(f"policy rule {policy.rule!r} needs a fallback provider")
        self.policy = policy
        self.primary = primary
        self.fallback = fallback
        self.on_drift = on_drift
        self._drift_checked = False

    # ------------------------------------------------------------ chargement
    @classmethod
    def from_file(cls, path: str | Path, *, primary: Provider,
                  fallback: Provider | None = None,
                  on_drift: OnDrift = "raise") -> "Router":
        return cls(Policy.read(Path(path)), primary=primary,
                   fallback=fallback, on_drift=on_drift)

    @classmethod
    def from_policy(cls, policy: Policy, **kwargs) -> "Router":
        return cls(policy, **kwargs)

    # --------------------------------------------------------------- decider
    def decide(self, input: str, question: Question) -> Decision:
        """Une decision pour une entree. `input`, pas `state` : le mot ne doit
        rien devoir au vocabulaire d'un fournisseur particulier."""
        self.policy.check_question(question)
        rule = self.policy.rule

        if rule == "always_fallback":
            # On n'interroge pas le primary : sa confiance ne servirait a rien.
            answer = self._ask(self.fallback, input, question, "fallback")
            return self._decide_from(answer, source="fallback", escalated=True,
                                     answers={"fallback": answer})

        primary_answer = self._ask(self.primary, input, question, "primary")
        answers: dict[str, Answer] = {"primary": primary_answer}

        if rule == "always_primary":
            return self._decide_from(primary_answer, source="primary",
                                     escalated=False, answers=answers)

        confidence = primary_answer.confidence
        if confidence is None:
            raise StalePolicyError(
                "the primary returned no confidence, so a confidence threshold "
                "cannot be applied. Measure again with a provider that exposes one.")
        if round_confidence(confidence) >= self.policy.threshold:
            return self._decide_from(primary_answer, source="primary",
                                     escalated=False, answers=answers)

        fallback_answer = self._ask(self.fallback, input, question, "fallback")
        answers["fallback"] = fallback_answer
        return self._decide_from(fallback_answer, source="fallback", escalated=True,
                                 answers=answers, confidence=confidence)

    def decide_many(self, inputs: Sequence[str], question: Question) -> list[Decision]:
        """Sequentiel. La concurrence appartient a l'appelant, qui connait ses
        propres limites de debit."""
        return [self.decide(item, question) for item in inputs]

    # --------------------------------------------------------------- interne
    def _ask(self, provider: Provider | None, input: str, question: Question,
             role: str) -> Answer:
        if provider is None:
            raise ValueError(f"no {role} provider configured")
        answer = provider.ask(input, question)
        self._check_drift(role, answer.model_id)
        return answer

    def _check_drift(self, role: str, model_id: str) -> None:
        if self.on_drift == "ignore" or self._drift_checked:
            return
        drift = self.policy.check_models(
            **{f"{role}_model_id": model_id})
        if not drift:
            return
        self._drift_checked = True
        message = ("this policy was measured on other model versions:\n  "
                   + "\n  ".join(drift)
                   + "\nRun `janus check` and re-measure if it matters.")
        if self.on_drift == "raise":
            raise StalePolicyError(message)
        warnings.warn(message, RuntimeWarning, stacklevel=3)

    def _decide_from(self, answer: Answer, *, source, escalated: bool,
                     answers: dict[str, Answer],
                     confidence: float | None = None) -> Decision:
        when = datetime.now(timezone.utc)
        costs = []
        for role, item in answers.items():
            provider = self.primary if role == "primary" else self.fallback
            costs.append(provider.cost_usd(item, when) if provider else None)
        # Un cout inconnu ne s'additionne pas : la somme devient inconnue.
        total = None if any(c is None for c in costs) else float(sum(costs))
        return Decision(
            label=answer.label,
            source=source,
            escalated=escalated,
            confidence=confidence if confidence is not None else answer.confidence,
            cost_usd=total,
            answers=answers,
        )


__all__ = ["Router", "NoPolicyError", "StalePolicyError"]
