"""Backends de baseline, derriere une interface unique.

Chaque fournisseur expose la meme methode :

    call(state) -> Completion(prediction, input_tokens, output_tokens, model_id)

Le runner ne connait rien d'autre. Ajouter un backend (Opus 5 en v2) est donc
un module de plus, pas une reecriture.

Les backends ne connaissent aucun dataset : ils recoivent une `Task` et en
derivent leur enonce. Tous les backends d'une meme tache recoivent donc le MEME
enonce -- memes classes, meme ordre, meme formulation -- et tous contraignent la
sortie a l'enum exact de ses classes, de sorte qu'une prediction hors liste soit
impossible par construction plutot que filtree apres coup.
"""

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from tasks import Task


def build_system_prompt(task: Task) -> str:
    """L'enonce constant, identique pour tous les backends d'une meme tache."""
    return (
        f"{task.instructions}\n\n"
        "Choose exactly one label from the list below. Each label name is followed "
        "by a description of what it covers.\n\n"
        + "\n".join(f"- {name}: {description}"
                    for name, description in task.criteria.items())
    )


def build_schema(task: Task) -> dict:
    """Contraint la sortie a l'enum exact des classes de la tache."""
    return {
        "type": "object",
        "properties": {"label": {"type": "string", "enum": list(task.label_names)}},
        "required": ["label"],
    }

RETRY_STATUSES = (429, 500, 502, 503, 529)
MAX_ATTEMPTS = 6


@dataclass(frozen=True)
class Completion:
    """Les quatre champs du contrat, plus ce qui est propre au fournisseur.

    `extra` est recopie tel quel en fin de ligne JSONL. C'est ce qui permet a un
    backend de logger ses propres compteurs -- decoupe de cache, tokens de
    raisonnement -- sans que le runner ait a les connaitre.
    """

    prediction: str
    input_tokens: int
    # Tokens de sortie FACTURABLES : sortie visible + raisonnement, que les
    # fournisseurs facturent au tarif de sortie.
    output_tokens: int
    model_id: str
    extra: dict = field(default_factory=dict)


class Provider(Protocol):
    name: str
    model: str

    def call(self, state: str) -> Completion: ...

    def cost_usd(self, completion: Completion, when: datetime) -> float | str: ...


def _flat_cost(pricing: dict[str, tuple[float, float]], completion: Completion) -> float | str:
    """Tarif a deux taux, entree et sortie, sans decoupe de cache ni heure.

    Indexe par la version EXACTE renvoyee par l'API : un identifiant inattendu
    donne "unknown" plutot qu'un chiffre invente.
    """
    if completion.model_id not in pricing:
        return "unknown"
    price_in, price_out = pricing[completion.model_id]
    return (completion.input_tokens / 1e6 * price_in
            + completion.output_tokens / 1e6 * price_out)


class GeminiProvider:
    """Google Gemini, endpoint /v1beta/interactions.

    Le structured output de la serie Gemini 3 passe par `response_format`
    sur cet endpoint, pas par `generateContent`.
    """

    name = "gemini"
    ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/interactions"

    # Tarif payant officiel releve le 2026-09-17 sur
    # https://ai.google.dev/gemini-api/docs/pricing
    # ATTENTION : tarif INTRODUCTIF pour les modeles 3.6 a 3.8, annonce
    # valable jusqu'au 2026-12-31. Tout cout de cascade calcule dessus porte
    # cette date de peremption.
    PRICING: dict[str, tuple[float, float]] = {
        "gemini-3.8-flash": (0.75, 3.75),
        "gemini-3.7-flash": (0.75, 3.75),
        "gemini-3.6-flash": (0.75, 3.75),
        "gemini-3.5-flash": (1.50, 9.00),
        "gemini-3.5-flash-lite": (0.30, 2.50),
    }

    # Quota du tier gratuit, lu dans le corps du 429 renvoye par l'API :
    #   metric generate_content_free_tier_requests, limit: 20
    # avec un delai de reprise d'environ 15 s, soit une fenetre glissante d'une
    # minute. On s'auto-limite juste en dessous plutot que de decouvrir la
    # limite en la heurtant.
    FREE_TIER_RPM = 20
    MIN_INTERVAL_S = 60.0 / FREE_TIER_RPM * 1.08

    def __init__(self, task: Task, model: str = "gemini-3.8-flash") -> None:
        self.model = model
        self.system_prompt = build_system_prompt(task)
        self.schema = build_schema(task)
        self.api_key = os.environ["GOOGLE_API_KEY"].strip()
        self._next_allowed = 0.0

    def _throttle(self) -> None:
        wait = self._next_allowed - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._next_allowed = time.monotonic() + self.MIN_INTERVAL_S

    def call(self, state: str) -> Completion:
        body = {
            "model": self.model,
            "system_instruction": self.system_prompt,
            "input": state,
            "response_format": {
                "type": "text",
                "mime_type": "application/json",
                "schema": self.schema,
            },
            # Pas de persistance serveur : chaque exemple est evalue seul, sans
            # etat partage qui pourrait faire fuir un exemple dans le suivant.
            "store": False,
        }
        payload = self._post(body)

        output = next(step for step in payload["steps"] if step["type"] == "model_output")
        text = next(block["text"] for block in output["content"] if block["type"] == "text")
        usage = payload["usage"]
        return Completion(
            prediction=json.loads(text)["label"],
            input_tokens=usage["total_input_tokens"],
            # Les tokens de raisonnement sont factures au tarif de sortie.
            output_tokens=usage["total_output_tokens"] + usage.get("total_thought_tokens", 0),
            # Gemini renvoie l'identifiant tel qu'envoye, sans version resolue.
            model_id=payload["model"],
        )

    def _post(self, body: dict) -> dict:
        request = urllib.request.Request(
            self.ENDPOINT,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": self.api_key},
        )
        last = None
        for attempt in range(MAX_ATTEMPTS):
            self._throttle()
            try:
                with urllib.request.urlopen(request, timeout=120) as response:
                    return json.load(response)
            except urllib.error.HTTPError as error:
                last = error
                if error.code not in RETRY_STATUSES:
                    raise SystemExit(
                        f"{self.name} : HTTP {error.code}\n{error.read().decode()[:800]}"
                    )
                detail = error.read().decode()
                # L'API indique elle-meme le delai a respecter ("Please retry in
                # 14.7s") : on l'utilise plutot que de tatonner en backoff.
                hinted = re.search(r"retry in ([0-9.]+)s", detail)
                wait = float(hinted.group(1)) + 1 if hinted else 2**attempt
                reason = "quota" if error.code == 429 else f"HTTP {error.code}"
                print(f"    {reason}, attente {wait:.0f}s")
                self._next_allowed = time.monotonic() + wait
        raise SystemExit(
            f"{self.name} : {MAX_ATTEMPTS} tentatives echouees, derniere HTTP "
            f"{last.code if last else '?'}. Un 429 persistant signale un quota epuise ; "
            "la reprise par id permet de repartir plus tard sans refaire les appels."
        )

    def cost_usd(self, completion: Completion, when: datetime) -> float | str:
        return _flat_cost(self.PRICING, completion)


class AnthropicProvider:
    """Claude Opus 5. Prevu pour la v2, des qu'un credit API est disponible.

    `temperature` est absent volontairement : le parametre est refuse par cette
    generation de modeles (400). `fallbacks` est absent aussi -- un repli
    servirait un autre modele au milieu du run.
    """

    name = "anthropic"
    MAX_TOKENS = 8000

    # Tarif officiel releve le 2026-09-17 sur
    # https://platform.claude.com/docs/en/about-claude/models/overview.md
    PRICING: dict[str, tuple[float, float]] = {
        "claude-opus-5": (5.0, 25.0),
    }

    def __init__(self, task: Task, model: str = "claude-opus-5") -> None:
        import anthropic  # importe ici : la v1 tourne sans le SDK Anthropic

        self.model = model
        self.system_prompt = build_system_prompt(task)
        self.schema = build_schema(task)
        self.client = anthropic.Anthropic()

    def call(self, state: str) -> Completion:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.MAX_TOKENS,
            system=self.system_prompt,
            messages=[{"role": "user", "content": state}],
            output_config={"format": {"type": "json_schema", "schema": self.schema}},
        )
        if response.stop_reason == "refusal":
            raise SystemExit(f"Refus du modele : {response.stop_details}")
        text = next(block.text for block in response.content if block.type == "text")
        return Completion(
            prediction=json.loads(text)["label"],
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            # Version exacte renvoyee par l'API, jamais l'alias envoye.
            model_id=response.model,
        )

    def cost_usd(self, completion: Completion, when: datetime) -> float | str:
        return _flat_cost(self.PRICING, completion)


class DeepSeekProvider:
    """DeepSeek V4-Pro, endpoint compatible OpenAI.

    Contrainte aux 77 labels par **tool call en mode strict** : c'est le seul
    mecanisme reellement contraignant disponible ici, verifie contre l'API.
    `response_format: {"type": "json_schema"}` est refuse ("This response_format
    type is unavailable now") et `json_object` ne garantit que du JSON valide,
    pas l'appartenance a l'enum -- il aurait fallu filtrer apres coup, ce qu'on
    s'interdit. `tool_choice` force est refuse en mode thinking ("Thinking mode
    does not support this tool_choice"), donc l'outil est propose en `auto` et
    l'absence d'appel d'outil fait echouer le run au lieu d'etre rattrapee.

    Le mode strict impose le base_url `/beta`.
    """

    name = "deepseek"
    BASE_URL = "https://api.deepseek.com/beta"
    TOOL_NAME = "submit_label"

    # Tarif officiel releve le 2026-09-17 sur
    # https://api-docs.deepseek.com/quick_start/pricing
    # (cache_hit, cache_miss, output) en $ par million de tokens.
    PRICING_OFF_PEAK: dict[str, tuple[float, float, float]] = {
        "deepseek-v4-pro": (0.022, 0.66, 1.98),
    }
    # Heures pleines : 01:00-04:00 et 06:00-10:00 UTC, du lundi au vendredi.
    # Le tarif y est exactement double.
    PEAK_MULTIPLIER = 2.0
    PEAK_HOURS = frozenset({1, 2, 3, 6, 7, 8, 9})

    def __init__(self, task: Task, model: str = "deepseek-v4-pro") -> None:
        from openai import OpenAI  # importe ici : les autres backends s'en passent

        self.model = model
        self.system_prompt = build_system_prompt(task)
        self.client = OpenAI(
            api_key=os.environ["DEEPSEEK_API_KEY"].strip(),
            base_url=self.BASE_URL,
            max_retries=5,
        )
        self.tools = [{
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": "Submit the chosen banking intent label.",
                "strict": True,
                "parameters": {**build_schema(task), "additionalProperties": False},
            },
        }]

    @classmethod
    def is_peak(cls, when: datetime) -> bool:
        """Heure pleine : lundi-vendredi UTC, 01:00-04:00 ou 06:00-10:00."""
        return when.weekday() < 5 and when.hour in cls.PEAK_HOURS

    def call(self, state: str) -> Completion:
        # `thinking` est actif par defaut et laisse tel quel : levier non explore.
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": state},
            ],
            tools=self.tools,
            tool_choice="auto",
        )
        choice = response.choices[0]
        if not choice.message.tool_calls:
            raise SystemExit(
                f"{self.name} : aucun appel d'outil (finish_reason="
                f"{choice.finish_reason}). La contrainte aux 77 labels ne s'est pas "
                "appliquee ; le run s'arrete plutot que de rattraper la sortie."
            )
        arguments = json.loads(choice.message.tool_calls[0].function.arguments)

        usage = response.usage
        details = usage.completion_tokens_details
        reasoning = getattr(details, "reasoning_tokens", None) if details else None
        return Completion(
            prediction=arguments["label"],
            input_tokens=usage.prompt_tokens,
            # completion_tokens inclut deja les tokens de raisonnement.
            output_tokens=usage.completion_tokens,
            # DeepSeek renvoie l'alias, sans version resolue.
            model_id=response.model,
            extra={
                # Le cache change le tarif d'entree d'un facteur 30 : sans cette
                # decoupe, le cout est faux.
                "cache_hit_tokens": usage.prompt_cache_hit_tokens,
                "cache_miss_tokens": usage.prompt_cache_miss_tokens,
                "reasoning_tokens": reasoning,
            },
        )

    def cost_usd(self, completion: Completion, when: datetime) -> float | str:
        if completion.model_id not in self.PRICING_OFF_PEAK:
            return "unknown"
        hit_rate, miss_rate, out_rate = self.PRICING_OFF_PEAK[completion.model_id]
        if self.is_peak(when):
            hit_rate *= self.PEAK_MULTIPLIER
            miss_rate *= self.PEAK_MULTIPLIER
            out_rate *= self.PEAK_MULTIPLIER
        return (completion.extra["cache_hit_tokens"] / 1e6 * hit_rate
                + completion.extra["cache_miss_tokens"] / 1e6 * miss_rate
                + completion.output_tokens / 1e6 * out_rate)


PROVIDERS: dict[str, type] = {
    "gemini": GeminiProvider,
    "anthropic": AnthropicProvider,
    "deepseek": DeepSeekProvider,
}
