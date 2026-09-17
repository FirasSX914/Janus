# Datasets figés

## Banking77

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

---

# Web of Science — WOS-46985

`wos_500.jsonl` — 500 résumés d'articles scientifiques, 145 classes sur 7 domaines.

## Provenance

| | |
|---|---|
| Dataset | Web of Science (Kowsari et al., *HDLTex*) — [Mendeley Data 9rw3vkcfy4, v6](https://data.mendeley.com/datasets/9rw3vkcfy4/6) |
| Fichier lu | `Meta-data/Data.xlsx` de l'archive |
| Population | 46 985 résumés |
| Échantillon | 500, tirage uniforme sans remise, `random.Random(42)` |
| Date de téléchargement | 2026-09-17 |
| **Licence** | **double** — CC BY 4.0 déclarée sur Mendeley, **et** une concession de type MIT dans le `ReadMe.txt` de l'archive (« Permission is hereby granted, free of charge… to use, copy, modify, merge, publish, distribute »), copyright Kamran Kowsari 2017 |
| Script | `src/prepare_data_wos.py` |

## Les trois systèmes de labels de l'archive se contredisent

C'est le point à connaître avant toute lecture des résultats.

| source dans l'archive | classes |
|---|---|
| `WOS46985/Y.txt` | **134** |
| couples `(YL1, YL2)` | **133** |
| `Meta-data`, couples `(Domain, area)` | **145** |

Le `ReadMe.txt` annonce 134. Les trois sont dans la même archive.

**`Y.txt` est inutilisable ici** : il ne contient que des indices numériques, et
leur correspondance vers des noms lisibles — nécessaires pour construire le
prompt — est **ambiguë sur 10 valeurs**. Par exemple `Y = 40` correspond à la
fois à `Medical/Depression` et à `Psychology/Depression` ; `Y = 71` correspond à
trois classes `Civil` distinctes (`Transparent Concrete`, `Smart Material`,
`Nano Concrete`).

On retient donc le `Meta-data`, seule source auto-cohérente : chaque ligne y
porte son propre `Domain` et sa propre `area`. **Conséquence assumée : les
chiffres publiés sur « WOS-46985 » portent sur la tâche à 134 classes de `Y.txt`
et ne sont pas des références externes comparables à nos résultats.**

Aucun filtrage n'est appliqué pour retomber sur 134. Retirer les 11 classes de
moins de 50 exemples y suffirait — mais choisir un seuil parce qu'il reproduit
le chiffre attendu serait exactement l'ajustement *post-hoc* que le protocole
s'interdit.

## Le label est un couple, pas une aire

`Depression` et `Schizophrenia` existent chacune sous **deux domaines**
différents (`Medical` et `Psychology`). L'aire seule n'identifie donc pas une
classe : le `gold_label` est le couple `Domain/area`.

## La vérité terrain est plus faible que celle de Banking77

À dire aussi explicitement que l'ambiguïté des labels de Banking77 l'est dans le
README principal.

**Les catégories viennent des métadonnées de publication, pas d'un annotateur
ayant lu chaque résumé.** Personne n'a examiné ce résumé-ci pour décider qu'il
relevait de cette aire-là. C'est de la vérité terrain produite par des humains,
au sens où des humains ont indexé ces articles, mais pas au sens où un
annotateur a porté un jugement par document — ce qui est le cas pour les
intentions de Banking77.

**Un résumé peut légitimement relever de deux domaines voisins.** La taxonomie
est hiérarchique à 7 parents et beaucoup de classes sont quasi synonymes à
l'intérieur d'un même parent. Un article de `CS/Machine learning` pourrait
relever de `CS/Algorithm design`, un article de `Medical/Depression` de
`Psychology/Depression`. Une part inconnue des erreurs mesurées tiendra à cette
ambiguïté plutôt qu'au modèle — c'est pourquoi l'analyse ventile les erreurs
selon qu'elles restent dans le même domaine parent ou le traversent.

## Composition

Effectifs **très inégaux** dans la population : de **1 à 750 exemples par
classe**, médiane 359. Onze classes comptent moins de 50 exemples, dont
`Civil/Underwater Windmill` (1), `Medical/Outdoor Health` (2) et
`Civil/Bamboo as a Building Material` (2).

Sur un tirage uniforme de 500 on attend donc **~3,4 exemples par classe**, contre
6,5 pour Banking77, et **la plupart des classes rares sont absentes** : 134 des
145 classes apparaissent dans l'échantillon. Sans effet sur l'analyse globale,
qui est la seule menée ; rédhibitoire pour toute analyse par classe.

Les résumés font 1 377 caractères en médiane, contre quelques mots pour une
requête Banking77 — ce qui pèse sur le coût par appel.

## Empreintes

```
sha256(archive Mendeley)  b787d484bff88b0dcdb3fa291d06ec9d2f025dc2a67ce1045d0c688cd96ccf8a
sha256(wos_500.jsonl)     23954a60f8ac255bdff021f006aa625b9d8742723d8afe5d53110ebe74fc131c
```

## Colonnes

| colonne | type | contenu |
|---|---|---|
| `id` | int | index de la ligne dans le classeur, hors en-tête, conservé tel quel |
| `text` | str | résumé, verbatim |
| `gold_label` | str | couple `Domain/area`, sans transformation (ex. `CS/Machine learning`) |
| `parent` | str | domaine parent seul, pour la ventilation des erreurs |

## Citation

Kowsari, Brown, Heidarysafa, Jafari Meimandi, Gerber, Barnes. *HDLTex:
Hierarchical Deep Learning for Text Classification*, ICMLA 2017.
