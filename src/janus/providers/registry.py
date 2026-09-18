"""Resolution d'une specification `"fournisseur:modele"` en instance.

    typesafe:jev-latest
    deepseek:deepseek-v4-pro
    anthropic:claude-opus-5
    openai_compat:mistral-large   (avec --base-url et --api-key-env)

Les backends sont importes paresseusement : installer Janus n'impose pas
d'installer les SDK de tous les fournisseurs.
"""

from __future__ import annotations

from typing import Any, Callable

from .base import Provider

_BUILDERS: dict[str, Callable[..., Provider]] = {}


def _typesafe(model: str, **kwargs) -> Provider:
    from .typesafe import TypeSafeProvider
    return TypeSafeProvider(model, **kwargs)


def _deepseek(model: str, **kwargs) -> Provider:
    from .openai_compat import DeepSeekProvider
    return DeepSeekProvider(model, **kwargs)


def _anthropic(model: str, **kwargs) -> Provider:
    from .anthropic import AnthropicProvider
    return AnthropicProvider(model, **kwargs)


def _openai_compat(model: str, **kwargs) -> Provider:
    from .openai_compat import OpenAICompatProvider
    return OpenAICompatProvider(model, **kwargs)


_BUILDERS.update({
    "typesafe": _typesafe,
    "deepseek": _deepseek,
    "anthropic": _anthropic,
    "openai_compat": _openai_compat,
})

PROVIDERS = tuple(sorted(_BUILDERS))


def register(name: str, builder: Callable[..., Provider]) -> None:
    """Ajoute un backend maison au registre."""
    _BUILDERS[name] = builder


def resolve(spec: str, **kwargs: Any) -> Provider:
    """`"deepseek:deepseek-v4-pro"` -> instance de `DeepSeekProvider`."""
    if ":" not in spec:
        raise ValueError(
            f"expected 'provider:model', got {spec!r}. "
            f"Known providers: {', '.join(sorted(_BUILDERS))}."
        )
    provider, model = spec.split(":", 1)
    if provider not in _BUILDERS:
        raise ValueError(
            f"unknown provider {provider!r}. "
            f"Known providers: {', '.join(sorted(_BUILDERS))}."
        )
    return _BUILDERS[provider](model, **kwargs)
