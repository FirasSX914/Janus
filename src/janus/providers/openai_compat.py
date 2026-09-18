"""Backends a API compatible OpenAI. DeepSeek en premier.

Migre de `experiments/providers.py`. Le mecanisme de contrainte a ete etabli
contre l'API, pas suppose :

- `response_format: {"type": "json_schema"}` est refuse par DeepSeek
  (*« This response_format type is unavailable now »*), et `json_object` ne
  garantit que du JSON valide, pas l'appartenance a l'enum -- il aurait fallu
  filtrer apres coup, ce qu'on s'interdit.
- `tool_choice` force est refuse en mode thinking
  (*« Thinking mode does not support this tool_choice »*), donc l'outil est
  propose en `auto` et l'absence d'appel d'outil fait echouer l'appel plutot
  que d'etre rattrapee.
- Le mode strict impose le base_url `/beta`.
"""

from __future__ import annotations

import json
import time
from datetime import datetime

from ..cost import cost_of, pricing_tier
from ..types import Answer, Question
from .base import render_prompt, render_schema

TOOL_NAME = "submit_label"


class ToolNotCalledError(RuntimeError):
    """Le modele n'a pas appele l'outil : la contrainte ne s'est pas appliquee."""


class OpenAICompatProvider:
    """Backend generique pour toute API compatible OpenAI."""

    name = "openai_compat"
    DEFAULT_BASE_URL = "https://api.openai.com/v1"

    def __init__(self, model: str, *, base_url: str | None = None,
                 api_key_env: str = "OPENAI_API_KEY", max_retries: int = 5,
                 name: str | None = None) -> None:
        import os

        from openai import OpenAI  # import tardif : dependance optionnelle

        self.model = model
        if name:
            self.name = name
        self._client = OpenAI(
            api_key=os.environ[api_key_env].strip(),
            base_url=base_url or self.DEFAULT_BASE_URL,
            max_retries=max_retries,
        )

    def _tools(self, question: Question) -> list[dict]:
        return [{
            "type": "function",
            "function": {
                "name": TOOL_NAME,
                "description": "Submit the chosen label.",
                "strict": True,
                "parameters": {**render_schema(question), "additionalProperties": False},
            },
        }]

    def ask(self, input: str, question: Question) -> Answer:
        started = time.perf_counter()
        response = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": render_prompt(question)},
                {"role": "user", "content": input},
            ],
            tools=self._tools(question),
            tool_choice="auto",
        )
        latency_ms = (time.perf_counter() - started) * 1000
        choice = response.choices[0]
        if not choice.message.tool_calls:
            raise ToolNotCalledError(
                f"{self.name}: no tool call (finish_reason={choice.finish_reason}). "
                "The label constraint did not apply; refusing to repair the output."
            )
        label = json.loads(choice.message.tool_calls[0].function.arguments)["label"]

        usage = response.usage
        details = getattr(usage, "completion_tokens_details", None)
        extra: dict = {"reasoning_tokens": getattr(details, "reasoning_tokens", None)}
        for field in ("prompt_cache_hit_tokens", "prompt_cache_miss_tokens"):
            value = getattr(usage, field, None)
            if value is not None:
                extra[field.replace("prompt_", "").replace("_tokens", "_tokens")] = value
        # Noms canoniques attendus par cost.py.
        if getattr(usage, "prompt_cache_hit_tokens", None) is not None:
            extra["cache_hit_tokens"] = usage.prompt_cache_hit_tokens
            extra["cache_miss_tokens"] = usage.prompt_cache_miss_tokens

        return Answer(
            label=label,
            # L'API renvoie l'alias, sans version resolue : faiblesse de
            # reproductibilite propre a ce fournisseur, consignee telle quelle.
            model_id=response.model,
            confidence=None,       # aucun fournisseur de ce type n'expose de
            distribution=None,     # distribution comparable
            input_tokens=usage.prompt_tokens,
            # completion_tokens inclut deja les tokens de raisonnement.
            output_tokens=usage.completion_tokens,
            latency_ms=round(latency_ms, 1),
            extra=extra,
        )

    def cost_usd(self, answer: Answer, when: datetime) -> float | None:
        return cost_of(answer, when)


class DeepSeekProvider(OpenAICompatProvider):
    """DeepSeek V4-Pro. Le mode strict impose le base_url `/beta`."""

    name = "deepseek"

    def __init__(self, model: str = "deepseek-v4-pro", **kwargs) -> None:
        kwargs.setdefault("base_url", "https://api.deepseek.com/beta")
        kwargs.setdefault("api_key_env", "DEEPSEEK_API_KEY")
        super().__init__(model, **kwargs)

    def ask(self, input: str, question: Question) -> Answer:
        answer = super().ask(input, question)
        # Le regime tarifaire de l'heure reelle de l'appel, consigne pour que le
        # cout d'une ligne soit recalculable depuis la ligne seule.
        extra = dict(answer.extra)
        extra["pricing_tier"] = pricing_tier(answer.model_id, datetime.now().astimezone())
        return Answer(**{**answer.__dict__, "extra": extra})
