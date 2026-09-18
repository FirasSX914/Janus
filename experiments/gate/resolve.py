"""Etape 2 : joindre chaque observation au texte du tour utilisateur.

Aucun appel API. La jointure ECHOUE EXPLICITEMENT plutot que de deviner.

    JOIN_OK         le prompt_id resout vers exactement un texte -> retenue
    JOIN_MISSING    prompt_id nul, transcript introuvable, aucun tour  -> exclue
    JOIN_AMBIGUOUS  plusieurs textes DISTINCTS pour ce prompt_id       -> exclue

Il n'y a aucun repli sur "le dernier message utilisateur". C'est exactement le
repli que l'ecriture asynchrone du transcript rend faux : il produirait un
USER_REQUEST plausible, attribue au mauvais tour, et invisible. Une exclusion
comptee vaut mieux qu'une ligne fausse silencieuse.

Les exclues ne disparaissent pas : elles vont dans gate_unresolved.jsonl avec
leur etat et leur motif, et le rapport en publie le compte ventile.

    python experiments/gate/resolve.py
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from extract import real_turn_text  # noqa: E402
from hook import _env_secrets, redact  # noqa: E402
from question import canonical, prompt_hash  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "results" / "raw"


def turns_of(path: Path) -> dict[str, set[str]]:
    """promptId -> ensemble des textes de tours utilisateur reels."""
    turns: dict[str, set[str]] = {}
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("type") != "user":
                continue
            text = real_turn_text(row)
            prompt_id = row.get("promptId")
            if text and prompt_id:
                turns.setdefault(prompt_id, set()).add(text)
    return turns


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--observations", type=Path, default=RAW / "gate_observations.jsonl")
    parser.add_argument("--out", type=Path, default=RAW / "gate_decisions.jsonl")
    parser.add_argument("--unresolved", type=Path, default=RAW / "gate_unresolved.jsonl")
    args = parser.parse_args(argv)

    if not args.observations.exists():
        parser.error(f"{args.observations} n'existe pas : lancer extract.py d'abord")

    secrets = _env_secrets()
    digest = prompt_hash()
    cache: dict[str, dict[str, set[str]]] = {}
    states: Counter[str] = Counter()
    per_source: Counter[tuple[str, str]] = Counter()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.observations.open(encoding="utf-8") as src, \
         args.out.open("w", encoding="utf-8", newline="\n") as ok, \
         args.unresolved.open("w", encoding="utf-8", newline="\n") as bad:

        for line in src:
            if not line.strip():
                continue
            observation = json.loads(line)
            source = observation.get("source", "?")
            state, reason, text = "JOIN_OK", None, None

            prompt_id = observation.get("prompt_id")
            transcript = observation.get("transcript_path")
            if not prompt_id:
                state, reason = "JOIN_MISSING", "no prompt_id: parent chain did not reach a user turn"
            elif not transcript or not Path(transcript).exists():
                state, reason = "JOIN_MISSING", "transcript file not found"
            else:
                if transcript not in cache:
                    cache[transcript] = turns_of(Path(transcript))
                candidates = cache[transcript].get(prompt_id, set())
                if not candidates:
                    state, reason = "JOIN_MISSING", "prompt_id absent from the transcript"
                elif len(candidates) > 1:
                    state = "JOIN_AMBIGUOUS"
                    reason = f"{len(candidates)} distinct user texts share this prompt_id"
                else:
                    text = next(iter(candidates))

            states[state] += 1
            per_source[(source, state)] += 1

            if state != "JOIN_OK":
                bad.write(json.dumps({**observation, "join_state": state,
                                      "join_reason": reason}, ensure_ascii=False) + "\n")
                continue

            arguments = json.dumps(observation.get("tool_input"), ensure_ascii=False, indent=2)
            ok.write(json.dumps({
                "id": observation["tool_use_id"],
                "source": source,
                "timestamp": observation.get("timestamp"),
                "session_id": observation.get("session_id"),
                "tool_name": observation.get("tool_name"),
                # La representation canonique est stockee TELLE QUELLE : c'est
                # elle qui part aux deux modeles, et l'analyse la relit sans la
                # reconstruire.
                "canonical": canonical(redact(text, secrets),
                                       observation.get("tool_name", ""),
                                       arguments),
                "prompt_hash": digest,
            }, ensure_ascii=False) + "\n")

    total = sum(states.values())
    print(f"observations lues : {total}")
    for state in ("JOIN_OK", "JOIN_MISSING", "JOIN_AMBIGUOUS"):
        n = states[state]
        print(f"  {state:15s} {n:5d}  ({n / total:.1%})" if total else f"  {state} {n}")
    print("\npar source :")
    for source in sorted({s for s, _ in per_source}):
        line = "  ".join(f"{state.split('_')[1]} {per_source[(source, state)]}"
                         for state in ("JOIN_OK", "JOIN_MISSING", "JOIN_AMBIGUOUS"))
        print(f"  {source:10s} {line}")
    print(f"\n{states['JOIN_OK']} decisions -> {args.out}")
    print(f"{total - states['JOIN_OK']} exclues  -> {args.unresolved}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
