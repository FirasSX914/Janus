"""Interface fournisseur, et l'enonce commun qui en derive.

Un fournisseur ne connait ni dataset ni politique. Il recoit une `Question` et
une entree, et rend un `Answer`. C'est tout ce que le routeur suppose de lui.

Le vocabulaire est volontairement neutre : `primary` et `fallback` ne disent pas
lequel est le meilleur. La mesure qui fonde ce paquet a trouve les deux ordres
selon le dataset, donc un vocabulaire qui prejugerait de la hierarchie serait
faux la moitie du temps.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Protocol, runtime_checkable

from ..types import Answer, Question


def render_prompt(question: Question) -> str:
    """L'enonce constant, identique pour tous les fournisseurs d'une question."""
    return (
        f"{question.instructions}\n\n"
        "Choose exactly one label from the list below. Each label name is followed "
        "by a description of what it covers.\n\n"
        + "\n".join(f"- {name}: {description}"
                    for name, description in question.criteria.items())
    )


def render_schema(question: Question) -> dict:
    """Contraint la sortie a l'enum exact des classes de la question."""
    return {
        "type": "object",
        "properties": {"label": {"type": "string", "enum": list(question.labels)}},
        "required": ["label"],
    }


def prompt_hash(question: Question) -> str:
    """SHA-256 de la partie CONSTANTE du prompt : enonce et criteres.

    L'entree n'y figure pas : elle change a chaque appel, et l'inclure donnerait
    une empreinte unique par ligne, incapable de detecter ce pour quoi elle
    existe -- un changement d'enonce entre la mesure et l'execution.

    Pas de `sort_keys` : reordonner les options change le corps de la requete,
    donc doit changer l'empreinte.
    """
    payload = {"instructions": question.instructions, "criteria": dict(question.criteria)}
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@runtime_checkable
class Provider(Protocol):
    """Le contrat que tout backend doit remplir."""

    name: str
    model: str

    def ask(self, input: str, question: Question) -> Answer:
        """Une decision, pour une entree et une question fermee."""
        ...

    def cost_usd(self, answer: Answer, when: datetime) -> float | None:
        """Cout de l'appel, ou `None` si le tarif du modele rendu est inconnu.

        `None` et non 0.0 : un cout inconnu ne doit jamais se confondre avec la
        gratuite dans une somme.
        """
        ...
