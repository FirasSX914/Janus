"""Objets publics de Janus.

Deux champs ne sont jamais fabriques pour uniformiser un type : `confidence` et
`distribution` valent `None` quand le fournisseur n'expose rien de comparable.
Inventer une valeur pour les rendre toujours presents reviendrait a comparer des
quantites produites par des mecanismes differents, ce que la mesure qui fonde ce
paquet s'interdit depuis le debut (voir docs/METHOD.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, Sequence

Source = Literal["primary", "fallback"]
Rule = Literal["primary_if_confidence_ge", "always_primary", "always_fallback"]
Verdict = Literal["route", "do_not_route"]


@dataclass(frozen=True)
class Question:
    """Une question fermee : un enonce et la liste exacte des reponses admises.

    `criteria` va du nom de classe a sa description. L'ordre d'insertion est
    l'ordre d'envoi et entre dans l'empreinte du prompt : le reordonner change
    la requete, donc doit changer l'empreinte.
    """

    instructions: str
    criteria: Mapping[str, str]

    @property
    def labels(self) -> tuple[str, ...]:
        return tuple(self.criteria)

    def __len__(self) -> int:
        return len(self.criteria)


@dataclass(frozen=True)
class Answer:
    """Ce qu'un fournisseur rend pour un appel."""

    label: str
    #: Version EXACTE renvoyee par l'API, jamais l'alias envoye.
    model_id: str
    confidence: float | None = None
    distribution: Mapping[str, float] | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    #: Compteurs propres au fournisseur : decoupe de cache, tokens de
    #: raisonnement, regime tarifaire. Recopies tels quels dans les JSONL.
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Decision:
    """Ce que `Router.decide` rend."""

    label: str
    source: Source
    escalated: bool
    confidence: float | None
    #: `None` quand le tarif du modele rendu est inconnu. Jamais 0.0 : un cout
    #: inconnu ne doit pas se confondre avec la gratuite.
    cost_usd: float | None
    answers: Mapping[str, Answer]


@dataclass(frozen=True)
class LevelRow:
    """Une valeur de confiance observee, et ce qu'elle a donne."""

    confidence: float
    n: int
    correct: int

    @property
    def accuracy(self) -> float:
        return self.correct / self.n


@dataclass(frozen=True)
class OperatingPoint:
    """Un seuil du balayage, et le point de fonctionnement qu'il produit."""

    threshold: float | None
    rule: Rule
    coverage: float
    escalation_rate: float
    n_escalated: int
    accuracy: float
    cost_total: float
    #: Mediane de la latence bout en bout d'une decision. Une escalade cumule
    #: les deux appels : on interroge le primary avant de pouvoir router.
    latency_p50_ms: float = 0.0


@dataclass(frozen=True)
class CalibrationReport:
    accuracy: float
    accuracy_ci: tuple[float, float]
    mean_confidence: float
    ece_by_level: float
    ece_by_level_ci: tuple[float, float]
    ece_equal_width: float
    brier: float
    brier_ci: tuple[float, float]
    levels: Sequence[LevelRow]


@dataclass(frozen=True)
class Measurement:
    """Ce que `measure` rend : une politique, et de quoi la relire."""

    policy: Any                     # janus.policy.Policy, evite un import circulaire
    levels: Sequence[LevelRow]
    calibration: CalibrationReport
    sweep: Sequence[OperatingPoint]
    verdict: Verdict
