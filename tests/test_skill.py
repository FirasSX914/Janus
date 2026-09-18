"""Le skill ne doit décrire que ce que la CLI fait vraiment.

Un skill est lu par un agent qui exécutera ce qu'il y trouve. Un drapeau
inventé n'y produit pas une phrase approximative, il produit une commande qui
échoue chez l'utilisateur. Deux fois aujourd'hui une copie manuelle de la
sortie a diverge du code ; ce fichier empêche la troisième.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from janus.agreement import BANNED, FORMULA  # noqa: E402
from janus.cli import build_parser  # noqa: E402

SKILL = ROOT / "skills" / "janus-decide" / "SKILL.md"


def parts() -> tuple[dict, str]:
    text = SKILL.read_text(encoding="utf-8")
    assert text.startswith("---\n"), "SKILL.md has no frontmatter"
    head, body = text[4:].split("\n---\n", 1)
    return yaml.safe_load(head), body


def known_flags() -> set[str]:
    """Tous les drapeaux de `janus` et de ses sous-commandes."""
    found: set[str] = set()

    def walk(parser):
        for action in parser._actions:
            found.update(action.option_strings)
            choices = getattr(action, "choices", None)
            if isinstance(choices, dict):          # sous-commandes seulement
                for choice in choices.values():
                    walk(choice)

    walk(build_parser())
    return found


# ------------------------------------------------------------------- forme
def test_frontmatter_matches_the_reference_pattern():
    meta, _ = parts()
    # Memes cles que skills/typesafe-ai/SKILL.md, dont ce skill suit le modele.
    assert set(meta) == {"name", "license", "description"}
    assert meta["name"] == "janus-decide"
    assert meta["license"] == "MIT"
    # La description dit QUAND s'en servir : c'est elle qui declenche le skill.
    assert "Use when" in meta["description"]


def test_skill_sits_where_the_plugin_manifests_point():
    import json
    marketplace = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
    assert marketplace["plugins"][0]["name"] == plugin["name"]
    assert SKILL.exists() and (SKILL.parent / "LICENSE").exists()


# ----------------------------------------------------- fidelite a la CLI
def janus_flags_cited(body: str) -> set[str]:
    """Les drapeaux cites SUR une commande janus, pas ceux de rg ou de fd."""
    # Recolle les continuations shell : sans cela, la deuxieme ligne d'une
    # commande a rallonge ne serait jamais reconnue comme une ligne janus.
    joined = re.sub(r"\\\n\s*", " ", body)
    cited: set[str] = set()
    for line in joined.splitlines():
        stripped = line.strip().removeprefix("$ ")
        if stripped.startswith("janus "):
            cited.update(re.findall(r"(?<![\w-])(--[a-z][a-z0-9-]+)", line))
    # Plus ceux cites en prose entre backticks, qui sont bien des janus.
    cited.update(re.findall(r"`(--[a-z][a-z0-9-]+)", body))
    return cited


def test_every_flag_the_skill_shows_exists():
    _, body = parts()
    unknown = sorted(janus_flags_cited(body) - known_flags())
    assert not unknown, (
        f"SKILL.md cites flags janus does not have: {unknown}. "
        "A skill is executed, not read: an invented flag becomes a failing "
        "command in someone's terminal.")


def test_every_subcommand_the_skill_shows_exists():
    _, body = parts()
    cited = {m for m in re.findall(r"(?m)^\s*janus ([a-z]+)", body)}
    real = set(build_parser()._subparsers._group_actions[0].choices)
    assert cited <= real, f"SKILL.md cites unknown subcommands: {sorted(cited - real)}"


def test_the_labels_shape_the_skill_shows_is_the_one_janus_reads(tmp_path):
    """L'exemple de fichier de labels doit vraiment se charger."""
    import json

    from janus.labels import from_json

    _, body = parts()
    block = re.search(r'```json\n(\{\n  "instructions".*?\n\})\n```', body, re.S)
    assert block, "SKILL.md no longer shows a labels file"
    path = tmp_path / "question.json"
    path.write_text(block.group(1), encoding="utf-8")
    question = from_json(path)
    assert len(question) == 3 and "APPROVE" in question.criteria


# --------------------------------------------------- vocabulaire impose
def test_skill_teaches_the_mandated_wording():
    _, body = parts()
    assert FORMULA in body, "the skill must carry the exact agreement formula"


def test_skill_states_the_prohibition_it_must_pass_on():
    """Le skill doit transmettre l'interdiction, pas seulement la respecter.

    Un scan en bloc du corps serait faux : la source `--dataset` porte un gold
    label, donc y parler de justesse est exact. L'interdiction ne vaut que pour
    la lecture d'un journal, et ce qui se teste est qu'elle soit enoncee.
    """
    _, body = parts()
    assert "refuses to print" in body
    for word in ("accuracy", "correct", "ground truth", "error rate"):
        assert f"`{word}`" in body, f"the skill does not name {word!r} as refused"


def test_log_section_never_promises_a_truth():
    """Dans la partie journal, aucune promesse de verite terrain."""
    _, body = parts()
    start = body.index("### From a log")
    section = re.sub(r"`[^`]*`", "", body[start:body.index("## Step 6")])
    assert not re.search(r"accurac(?:y|ies)|ground[ -]truth",
                         section, re.IGNORECASE)


def test_skill_forbids_inventing_inputs():
    _, body = parts()
    lowered = body.lower()
    meta, _ = parts()
    assert "never invent" in meta["description"].lower()
    for obligation in ("may be invented", "--estimate",
                       "majority-class baseline", "stratified"):
        assert obligation.lower() in lowered, f"the skill drops {obligation!r}"


def test_skill_covers_both_sources():
    _, body = parts()
    assert "--dataset" in body and "--log" in body
    assert "DO NOT ROUTE" in body, "the skill must say that not routing is a result"


@pytest.mark.parametrize("claim", [
    "pip install janus-decide",
    "--sample N\n--seed S" .replace("\n", " "),   # les deux vont ensemble
])
def test_install_and_sampling_claims_are_present(claim):
    _, body = parts()
    assert claim.split()[0] in body
