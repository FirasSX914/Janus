"""Backends, derriere une interface unique.

Chacun est importe paresseusement par le registre : installer Janus n'impose pas
d'installer les SDK de tous les fournisseurs.
"""

from .base import Provider, prompt_hash, render_prompt, render_schema
from .registry import PROVIDERS, register, resolve

__all__ = ["Provider", "prompt_hash", "render_prompt", "render_schema",
           "PROVIDERS", "register", "resolve"]
