"""TypeSafe System One (Jev).

Migre de `experiments/run_jev.py`. Trois regles etablies contre l'API et
conservees telles quelles :

- `model_id` vient de `response.model`, la version resolue, jamais l'alias
  envoye. Logger l'alias rendrait deux runs separes par une release
  indistinguables.
- La latence est mesuree cote client : la reponse n'en porte aucune trace.
- On passe par `response.choices[...]`, jamais `response.answers[...]`, qui
  melange les types -- un `NoulAnswer` n'a pas de champ `confidence`.
"""

from __future__ import annotations

import time
from datetime import datetime

from ..cost import cost_of
from ..types import Answer, Question


class TypeSafeProvider:
    name = "typesafe"

    def __init__(self, model: str = "jev-latest", *, question_id: str = "label",
                 timeout: float = 30.0) -> None:
        from typesafe_sdk import TypeSafeClient  # import tardif : dependance optionnelle

        self.model = model
        self.question_id = question_id
        self._client = TypeSafeClient(timeout=timeout)

    def ask(self, input: str, question: Question) -> Answer:
        from typesafe_sdk import Choice

        started = time.perf_counter()
        response = self._client.system_one(
            state=input,
            model=self.model,
            questions={self.question_id: Choice(instructions=question.instructions,
                                                criteria=dict(question.criteria))},
        )
        latency_ms = (time.perf_counter() - started) * 1000
        answer = response.choices[self.question_id]
        return Answer(
            label=answer.choice,
            model_id=response.model,
            confidence=answer.confidence,
            # Stockee brute, sans renormalisation : l'API renvoie des valeurs au
            # centieme et une partie des lignes somme a 0,99.
            distribution=dict(answer.probabilities),
            input_tokens=response.usage.input_tokens,
            output_tokens=getattr(response.usage, "output_tokens", 0),
            latency_ms=round(latency_ms, 1),
        )

    def cost_usd(self, answer: Answer, when: datetime) -> float | None:
        return cost_of(answer, when)
