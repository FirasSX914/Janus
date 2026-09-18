"""Tarification par appel, depuis les tokens reellement consommes.

Migre de l'experience (`experiments/providers.py`), sans changement de methode.

Deux regles que la mesure a rendues non negociables :

- **La decoupe du cache n'est pas un detail.** Chez DeepSeek l'entree en cache
  hit coute trente fois moins qu'en miss. Sur Banking77, ou le prefixe constant
  dominait le prompt, ignorer la decoupe aurait surestime le cout d'un facteur
  4,5 ; sur Web of Science, d'un facteur 2,7.
- **Un tarif inconnu rend `None`, jamais 0.0.** Un identifiant de modele absent
  de la table donne un cout inconnu, qui ne doit pas disparaitre dans une somme.
"""

from __future__ import annotations

from datetime import datetime

from .types import Answer

# --------------------------------------------------------------------------
# Tarifs releves le 2026-09-17 sur les pages officielles des fournisseurs.
# Indexes par la version EXACTE renvoyee par l'API.
# --------------------------------------------------------------------------

#: $ par million de tokens, (entree, sortie).
FLAT_PRICING: dict[str, tuple[float, float]] = {
    # https://docs.typesafe.ai/models — 42 $/Btok en entree, sortie gratuite.
    "jev-1.13.0": (0.042, 0.0),
    # https://platform.claude.com/docs/en/about-claude/models/overview.md
    "claude-opus-5": (5.0, 25.0),
    # https://ai.google.dev/gemini-api/docs/pricing
    # ATTENTION : tarif introductif annonce valable jusqu'au 2026-12-31.
    "gemini-3.8-flash": (0.75, 3.75),
    "gemini-3.5-flash": (1.50, 9.00),
    "gemini-3.5-flash-lite": (0.30, 2.50),
}

#: $ par million de tokens, (cache hit, cache miss, sortie), hors heures pleines.
CACHED_PRICING: dict[str, tuple[float, float, float]] = {
    # https://api-docs.deepseek.com/quick_start/pricing
    "deepseek-v4-pro": (0.022, 0.66, 1.98),
}

#: Heures pleines DeepSeek : 01:00-04:00 et 06:00-10:00 UTC, du lundi au
#: vendredi, au tarif exactement double.
PEAK_HOURS = frozenset({1, 2, 3, 6, 7, 8, 9})
PEAK_MULTIPLIER = 2.0
PEAK_MODELS = frozenset(CACHED_PRICING)


def is_peak(model_id: str, when: datetime) -> bool:
    return (model_id in PEAK_MODELS
            and when.weekday() < 5
            and when.hour in PEAK_HOURS)


def cost_of(answer: Answer, when: datetime) -> float | None:
    """Cout d'un appel, ou `None` si le tarif du modele rendu est inconnu."""
    model_id = answer.model_id

    if model_id in CACHED_PRICING:
        hit_rate, miss_rate, out_rate = CACHED_PRICING[model_id]
        if is_peak(model_id, when):
            hit_rate *= PEAK_MULTIPLIER
            miss_rate *= PEAK_MULTIPLIER
            out_rate *= PEAK_MULTIPLIER
        hit = answer.extra.get("cache_hit_tokens")
        miss = answer.extra.get("cache_miss_tokens")
        if hit is None or miss is None:
            # Sans la decoupe, on ne sait pas facturer l'entree correctement.
            return None
        return (hit / 1e6 * hit_rate
                + miss / 1e6 * miss_rate
                + answer.output_tokens / 1e6 * out_rate)

    if model_id in FLAT_PRICING:
        price_in, price_out = FLAT_PRICING[model_id]
        return (answer.input_tokens / 1e6 * price_in
                + answer.output_tokens / 1e6 * price_out)

    return None


def pricing_tier(model_id: str, when: datetime) -> str:
    return "peak" if is_peak(model_id, when) else "off_peak"
