"""Claude, via l'API Anthropic.

Migre de `experiments/providers.py`. Deux absences deliberees :

- **`temperature` n'est pas passe.** Le parametre est retire de l'API sur cette
  generation de modeles et une requete qui le contient renvoie une 400. Aucune
  reproductibilite exacte n'est donc revendiquee ; la documentation officielle
  precise par ailleurs que la ou `temperature = 0` existait, il n'a jamais
  garanti des sorties identiques.
- **`fallbacks` n'est pas active**, a l'encontre de la recommandation generale
  pour ce modele : un repli servirait un autre modele au milieu d'une mesure,
  ce qu'une comparaison doit interdire.
"""

from __future__ import annotations

import json
import time
from datetime import datetime

from ..cost import cost_of
from ..types import Answer, Question
from .base import render_prompt, render_schema


class RefusalError(RuntimeError):
    """Le modele a refuse : on s'arrete plutot que de consigner une non-reponse."""


class AnthropicProvider:
    name = "anthropic"
    MAX_TOKENS = 8000

    def __init__(self, model: str = "claude-opus-5", *, max_tokens: int | None = None) -> None:
        import anthropic  # import tardif : dependance optionnelle

        self.model = model
        self.max_tokens = max_tokens or self.MAX_TOKENS
        self._client = anthropic.Anthropic()

    def ask(self, input: str, question: Question) -> Answer:
        started = time.perf_counter()
        response = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=render_prompt(question),
            messages=[{"role": "user", "content": input}],
            output_config={"format": {"type": "json_schema",
                                      "schema": render_schema(question)}},
        )
        latency_ms = (time.perf_counter() - started) * 1000
        if response.stop_reason == "refusal":
            raise RefusalError(f"anthropic refused: {response.stop_details}")
        text = next(block.text for block in response.content if block.type == "text")
        return Answer(
            label=json.loads(text)["label"],
            # Version exacte renvoyee par l'API, jamais l'alias envoye.
            model_id=response.model,
            confidence=None,
            distribution=None,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            latency_ms=round(latency_ms, 1),
        )

    def cost_usd(self, answer: Answer, when: datetime) -> float | None:
        return cost_of(answer, when)
