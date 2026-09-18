"""Source d'entree : un journal de decisions deja prises, sans etiquette d'or.

La source `--dataset` mesure une justesse contre un gold label. Celle-ci n'en a
pas : le journal dit ce qu'un modele de decision a REPONDU et avec quelle
confiance, jamais s'il avait raison. Ce qu'on en tire est donc un ACCORD avec un
modele de reference, et cette distinction tient tout le module.

Les noms de champs sont des drapeaux, pas des conventions : un journal vient
d'un autre logiciel et ne doit pas avoir a etre renomme pour entrer ici. Les
valeurs par defaut sont celles qu'ecrit `janus measure` lui-meme, pour qu'un
fichier brut de Janus se rejoue comme journal sans configuration.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LogSpec:
    """Ou lire chaque valeur dans une ligne de journal."""

    input_field: str = "text"
    decision_field: str = "prediction"
    confidence_field: str = "confidence"
    id_field: str | None = None

    def describe(self) -> str:
        return (f"input={self.input_field} decision={self.decision_field} "
                f"confidence={self.confidence_field}")


@dataclass(frozen=True)
class LogRow:
    """Une decision deja prise. Pas de `gold_label` : il n'en existe pas."""

    id: str
    input: str
    decision: str
    confidence: float


class LogFormatError(ValueError):
    """Le journal ne porte pas les champs annonces."""


def _pick(record: dict, field: str, line_no: int, path: Path):
    if field not in record:
        raise LogFormatError(
            f"{path}:{line_no} has no field {field!r}.\n"
            f"  fields present: {', '.join(sorted(record)) or '(none)'}\n"
            "  Point --input-field / --decision-field / --confidence-field at the "
            "names this log actually uses; Janus does not rename anyone's log.")
    return record[field]


def read_log(path: Path, spec: LogSpec) -> list[LogRow]:
    """Lit le journal, en echouant sur le premier champ manquant.

    Echouer tot et en nommant le champ vaut mieux que sauter les lignes
    incompletes : un journal a moitie lu donnerait une mesure a moitie fausse,
    sans que rien ne le signale.
    """
    rows: list[LogRow] = []
    seen: set[str] = set()
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise LogFormatError(f"{path}:{line_no} is not valid JSON: {error}") from error
        if not isinstance(record, dict):
            raise LogFormatError(f"{path}:{line_no} is not a JSON object")

        raw_confidence = _pick(record, spec.confidence_field, line_no, path)
        try:
            confidence = float(raw_confidence)
        except (TypeError, ValueError) as error:
            raise LogFormatError(
                f"{path}:{line_no} field {spec.confidence_field!r} is "
                f"{raw_confidence!r}, which is not a number") from error
        if not 0.0 <= confidence <= 1.0:
            raise LogFormatError(
                f"{path}:{line_no} confidence {confidence} is outside [0, 1]. "
                "Janus reads a confidence, not a score on another scale.")

        identifier = (str(_pick(record, spec.id_field, line_no, path))
                      if spec.id_field else str(line_no))
        if identifier in seen:
            raise LogFormatError(
                f"{path}:{line_no} repeats id {identifier!r}. Ids must be unique, "
                "otherwise the same decision is measured twice.")
        seen.add(identifier)

        rows.append(LogRow(
            id=identifier,
            input=str(_pick(record, spec.input_field, line_no, path)),
            decision=str(_pick(record, spec.decision_field, line_no, path)),
            confidence=confidence,
        ))

    if not rows:
        raise LogFormatError(f"{path} holds no decision")
    return rows


def observed_decisions(rows: list[LogRow]) -> list[str]:
    """Les classes REELLEMENT vues dans le journal, dans l'ordre d'apparition.

    L'ordre compte : il entre dans le `prompt_hash` du modele de reference, donc
    reordonner les options changerait la question posee.
    """
    seen: list[str] = []
    for row in rows:
        if row.decision not in seen:
            seen.append(row.decision)
    return seen
