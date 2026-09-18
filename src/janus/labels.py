"""Chargement d'une `Question` depuis un fichier.

Le format par defaut est du JSON. Executer du code arbitraire depuis une ligne
de commande est un mauvais defaut : le chargeur de module Python existe, mais il
faut le demander explicitement avec `--labels-module`.

Deux formes acceptees :

    {"instructions": "...", "labels": {"nom": "description", ...}}
    {"instructions": "...", "labels": ["nom", "nom", ...]}

Une liste nue donne des descriptions vides : le nom de classe est alors seul a
porter le sens, ce qui est acceptable quand il est deja explicite.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from .types import Question

DEFAULT_INSTRUCTIONS = "Which label applies to this input?"


def from_json(path: Path) -> Question:
    data = json.loads(path.read_text(encoding="utf-8"))
    if "labels" not in data:
        raise ValueError(f"{path}: missing the 'labels' key")
    labels = data["labels"]
    if isinstance(labels, list):
        criteria = {str(name): "" for name in labels}
    elif isinstance(labels, dict):
        criteria = {str(name): str(description or "")
                    for name, description in labels.items()}
    else:
        raise ValueError(f"{path}: 'labels' must be a list or an object")
    if not criteria:
        raise ValueError(f"{path}: 'labels' is empty")
    return Question(instructions=data.get("instructions", DEFAULT_INSTRUCTIONS),
                    criteria=criteria)


def from_module(path: Path) -> Question:
    """Charge un module Python exposant INSTRUCTIONS et CRITERIA.

    A demander explicitement : ce chemin execute le fichier.
    """
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"{path}: not an importable Python module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "CRITERIA"):
        raise ValueError(f"{path}: the module exposes no CRITERIA mapping")
    return Question(
        instructions=getattr(module, "INSTRUCTIONS", DEFAULT_INSTRUCTIONS),
        criteria=dict(module.CRITERIA),
    )
