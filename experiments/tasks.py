"""Registre des tâches. Une tâche = un dataset figé + un module de labels.

Les runners ne connaissent pas les datasets : ils prennent `--task` et lisent
ici le chemin des données, les instructions et les critères. Ajouter un dataset
est donc une entrée dans `TASKS` plus deux fichiers, pas une copie de runner.

`prompt_hash` est calculé sur la partie CONSTANTE du prompt — instructions plus
critères — par la même formule pour toutes les tâches. Deux tâches aux labels
différents produisent donc nécessairement des hash différents : c'est attendu,
et ce n'est pas une rupture de protocole. Ce que le hash garantit est qu'à
l'intérieur d'un fichier de résultats toutes les lignes ont reçu le même énoncé,
et que les runners Jev et frontier d'une même tâche ont reçu le même.
Voir docs/METHOD.md.
"""

import hashlib
import importlib
import json
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# nom de tâche -> (module de labels, fichier de données)
TASKS: dict[str, tuple[str, str]] = {
    "banking77": ("labels", "banking77_500.jsonl"),
    "wos": ("labels_wos", "wos_500.jsonl"),
}


@dataclass(frozen=True)
class Task:
    name: str
    data_path: Path
    instructions: str
    criteria: dict[str, str]
    label_names: tuple[str, ...]
    # Domaine parent de chaque classe, quand la taxonomie en a un. Sert
    # uniquement à ventiler les erreurs ; n'entre jamais dans le prompt_hash.
    parents: dict[str, str] | None

    @property
    def prompt_hash(self) -> str:
        constant = {"instructions": self.instructions, "criteria": self.criteria}
        payload = json.dumps(constant, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def examples(self) -> list[dict]:
        return [
            json.loads(line)
            for line in self.data_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def out_path(self, runner: str) -> Path:
        return ROOT / "results" / "raw" / f"{runner}_{self.name}_500.jsonl"


def load(name: str) -> Task:
    module_name, data_file = TASKS[name]
    module = importlib.import_module(module_name)
    return Task(
        name=name,
        data_path=ROOT / "data" / data_file,
        instructions=module.INSTRUCTIONS,
        criteria=module.CRITERIA,
        label_names=module.LABEL_NAMES,
        parents=getattr(module, "PARENTS", None),
    )
