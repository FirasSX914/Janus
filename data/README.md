# Dataset figé

`banking77_500.jsonl` — 500 exemples du split **test** de Banking77.

## Provenance

| | |
|---|---|
| Dataset | Banking77 — [PolyAI/banking77](https://huggingface.co/datasets/PolyAI/banking77) sur HuggingFace |
| Source amont | [`banking_data/test.csv`](https://raw.githubusercontent.com/PolyAI-LDN/task-specific-datasets/master/banking_data/test.csv), dépôt PolyAI-LDN/task-specific-datasets |
| Split | `test` — 3080 exemples, 77 labels |
| Échantillon | 500 exemples, tirage uniforme sans remise, `random.Random(42)` |
| Date de téléchargement | 2026-09-17 |
| Licence | CC BY 4.0 (déclarée sur la fiche HuggingFace) |
| Script | `src/prepare_data.py` |

PolyAI/banking77 est un dataset à script : depuis la fin du support des scripts
par `datasets`, il n'est plus chargeable par `load_dataset`, et son loader
téléchargeait de toute façon `test.csv` depuis GitHub. `prepare_data.py` lit
donc directement cette source amont, avec le même dialecte CSV que le loader
d'origine — ce qui évite d'installer `datasets`/pyarrow/pandas, exclus par le
projet.

## Empreintes

```
sha256(test.csv)              d12d6e3bc4c3103966ae786dc435913c0c563dfa328f5a3646d0e62cfeeb474d
sha256(banking77_500.jsonl)   33547bc2c3453057fbeb50cc5cb68da32c6da3c1b79b5deae47567c20fcf0bb6
```

`test.csv` est servi depuis la branche `master` d'un dépôt GitHub, donc mutable
en principe. L'empreinte ci-dessus est la garantie : si un futur
`python src/prepare_data.py` ne la reproduit pas, la source amont a changé et
c'est le JSONL commité qui fait foi, pas le re-téléchargement.

## Colonnes

| colonne | type | contenu |
|---|---|---|
| `id` | int | index de la ligne dans le split test d'origine (0-based), conservé tel quel |
| `text` | str | énoncé client, verbatim |
| `gold_label` | str | label du dataset d'origine, **sans transformation** (ex. `card_arrival`) |

Les `id` ne sont pas contigus : ce sont les index d'origine, ce qui permet de
remonter à la ligne exacte du CSV amont. Ils sont triés par ordre croissant,
donc l'ordre du fichier ne dépend que de la graine, pas de l'ordre de tirage.

## Composition

Les 77 labels sont représentés, mais le tirage est **uniforme, non stratifié** :
entre 1 et 12 exemples par label. Suffisant pour la calibration globale et les
courbes risk–coverage ; trop mince pour une analyse par label, qui demanderait
un tirage stratifié et un autre fichier.

## Citation

Casanueva, Temčinas, Gerz, Henderson, Vulić. *Efficient Intent Detection with
Dual Sentence Encoders*, 2020. [arXiv:2003.04807](https://arxiv.org/abs/2003.04807)
