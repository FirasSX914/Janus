"""`janus.json` : lecture, ecriture, validation, detection de derive.

Une politique n'est pas une preference, c'est le compte rendu d'une mesure. Elle
porte donc ce sur quoi elle a ete mesuree -- l'empreinte de l'enonce, les
versions RESOLUES des modeles, l'empreinte du dataset -- pour qu'on puisse
verifier qu'elle s'applique encore, et la table des niveaux observes, pour qu'on
puisse rejouer le balayage a une autre cible sans refaire un seul appel.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .types import LevelRow, OperatingPoint, Question, Rule, Verdict
from .providers.base import prompt_hash

POLICY_VERSION = 1
#: Les valeurs de confiance vivent sur une grille au centieme. Un seuil hors
#: grille designerait une valeur que l'API ne sait pas produire.
GRID = 0.01


class PolicyError(Exception):
    """Base des erreurs de politique."""


class NoPolicyError(PolicyError):
    """Aucune politique : Janus refuse de router sur une valeur inventee."""


class InvalidPolicyError(PolicyError):
    """Le fichier existe mais ne decrit pas une politique utilisable."""


class StalePolicyError(PolicyError):
    """Ce qui tourne n'est plus ce qui a ete mesure."""


@dataclass(frozen=True)
class ModelRef:
    provider: str
    sent: str
    resolved: str

    def to_json(self) -> dict:
        return {"provider": self.provider, "sent": self.sent, "resolved": self.resolved}

    @staticmethod
    def from_json(data: Mapping[str, Any]) -> "ModelRef":
        return ModelRef(data["provider"], data["sent"], data["resolved"])


@dataclass(frozen=True)
class Policy:
    """Le contenu de `janus.json`."""

    prompt_hash: str
    n_classes: int
    primary: ModelRef
    fallback: ModelRef | None
    route: bool
    rule: Rule
    threshold: float | None
    operating_point: Mapping[str, Any]
    levels: Sequence[LevelRow] = field(default_factory=tuple)
    ceiling: Mapping[str, Any] = field(default_factory=dict)
    measured_on: Mapping[str, Any] = field(default_factory=dict)
    caveats: Sequence[str] = field(default_factory=tuple)
    reason: str = ""
    created_at: str = ""
    version: int = POLICY_VERSION

    # ---------------------------------------------------------------- checks
    def validate(self) -> None:
        if self.version != POLICY_VERSION:
            raise InvalidPolicyError(
                f"policy version {self.version}, this build reads {POLICY_VERSION}")
        if self.rule == "primary_if_confidence_ge":
            if self.threshold is None:
                raise InvalidPolicyError("rule needs a threshold, none is set")
            on_grid = abs(self.threshold / GRID - round(self.threshold / GRID)) < 1e-9
            if not on_grid:
                raise InvalidPolicyError(
                    f"threshold {self.threshold} is off the {GRID} grid; the "
                    "confidence scale cannot express it")
        elif self.threshold is not None:
            raise InvalidPolicyError(f"rule {self.rule!r} must not carry a threshold")
        if self.rule != "always_primary" and self.fallback is None:
            raise InvalidPolicyError(f"rule {self.rule!r} needs a fallback model")

    def check_question(self, question: Question) -> None:
        """L'enonce execute doit etre celui qui a ete mesure."""
        current = prompt_hash(question)
        if current != self.prompt_hash:
            raise StalePolicyError(
                "the question is not the one this policy was measured on\n"
                f"  measured : {self.prompt_hash}\n"
                f"  current  : {current}\n"
                "Re-run `janus measure`; a threshold measured on another "
                "statement does not carry over.")

    def check_models(self, *, primary_model_id: str | None = None,
                     fallback_model_id: str | None = None) -> list[str]:
        """Rend la liste des derives constatees, vide si tout concorde."""
        drift: list[str] = []
        if primary_model_id and primary_model_id != self.primary.resolved:
            drift.append(f"primary: measured on {self.primary.resolved}, "
                         f"now answering {primary_model_id}")
        if (fallback_model_id and self.fallback
                and fallback_model_id != self.fallback.resolved):
            drift.append(f"fallback: measured on {self.fallback.resolved}, "
                         f"now answering {fallback_model_id}")
        return drift

    # ------------------------------------------------------------------- io
    def to_json(self) -> dict:
        return {
            "janus_policy_version": self.version,
            "created_at": self.created_at,
            "question": {"prompt_hash": self.prompt_hash, "n_classes": self.n_classes},
            "models": {
                "primary": self.primary.to_json(),
                "fallback": self.fallback.to_json() if self.fallback else None,
            },
            "measured_on": dict(self.measured_on),
            "decision": {"route": self.route, "rule": self.rule,
                         "threshold": self.threshold, "reason": self.reason},
            "operating_point": dict(self.operating_point),
            "ceiling": dict(self.ceiling),
            "levels": [{"confidence": row.confidence, "n": row.n, "correct": row.correct}
                       for row in self.levels],
            "caveats": list(self.caveats),
        }

    def write(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_json(), indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")

    @staticmethod
    def from_json(data: Mapping[str, Any]) -> "Policy":
        decision = data["decision"]
        models = data["models"]
        policy = Policy(
            prompt_hash=data["question"]["prompt_hash"],
            n_classes=data["question"]["n_classes"],
            primary=ModelRef.from_json(models["primary"]),
            fallback=ModelRef.from_json(models["fallback"]) if models.get("fallback") else None,
            route=decision["route"],
            rule=decision["rule"],
            threshold=decision.get("threshold"),
            operating_point=data.get("operating_point", {}),
            levels=tuple(LevelRow(row["confidence"], row["n"], row["correct"])
                         for row in data.get("levels", [])),
            ceiling=data.get("ceiling", {}),
            measured_on=data.get("measured_on", {}),
            caveats=tuple(data.get("caveats", [])),
            reason=decision.get("reason", ""),
            created_at=data.get("created_at", ""),
            version=data.get("janus_policy_version", POLICY_VERSION),
        )
        policy.validate()
        return policy

    @staticmethod
    def read(path: Path) -> "Policy":
        if not path.exists():
            raise NoPolicyError(
                f"{path} does not exist. Run `janus measure` on your own data: "
                "Janus ships no default threshold, because none of the routing "
                "parameters measured on one dataset carried over to another.")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise InvalidPolicyError(f"{path} is not valid JSON: {error}") from error
        return Policy.from_json(data)


def build(*, question: Question, primary: ModelRef, fallback: ModelRef | None,
          point: OperatingPoint, verdict: Verdict, reason: str,
          levels: Sequence[LevelRow], oracle: float, unreachable: int,
          measured_on: Mapping[str, Any], baselines: Mapping[str, float],
          caveats: Sequence[str] = ()) -> Policy:
    policy = Policy(
        prompt_hash=prompt_hash(question),
        n_classes=len(question),
        primary=primary,
        fallback=fallback,
        route=verdict == "route",
        rule=point.rule,
        threshold=point.threshold,
        operating_point={
            "accuracy": point.accuracy,
            "coverage": point.coverage,
            "escalation_rate": point.escalation_rate,
            "cost_total": point.cost_total,
            "latency_p50_ms": point.latency_p50_ms,
            "baselines": dict(baselines),
        },
        levels=tuple(levels),
        ceiling={"oracle_accuracy": oracle, "unreachable_rows": unreachable},
        measured_on=dict(measured_on),
        caveats=tuple(caveats),
        reason=reason,
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    )
    policy.validate()
    return policy
