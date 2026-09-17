# Méthode

## Contrat du JSONL de run

Une ligne par exemple. `run_jev.py` et `run_frontier.py` écrivent ces colonnes :

```
id, input, gold, predicted, confidence, probabilities,
margin_top2, entropy_norm, ratio_top2,
latency_ms, input_tokens, model_id, prompt_hash, run_date
```

Trois règles pour les remplir, vérifiées sur les appels de `probe.py` :

1. **`model_id` = `response.model`**, jamais la chaîne envoyée. On envoie l'alias
   `jev-latest`, l'API répond la version résolue (`jev-1.13.0` au 2026-09-17).
   Logger l'alias rendrait deux runs séparés par une release indistinguables et
   ferait perdre au benchmark sa reproductibilité.
2. **`latency_ms` mesuré côté client** avec `time.perf_counter()` autour de
   l'appel. La réponse ne porte aucune information de latence.
3. **Toujours `response.choices[...]`**, jamais `response.answers[...]`.
   `answers` mélange les types ; un `NoulAnswer` n'a pas de champ `confidence`
   et tout code qui suppose le contraire casse sur les binaires. Passer par
   `choices` rend l'erreur impossible par construction.

`probabilities` est stocké brut, tel que renvoyé par l'API, sans renormalisation.

## Trois statistiques descriptives alternatives

En plus de `confidence`, chaque ligne porte trois statistiques calculées depuis
`probabilities` brut. Soient `p1 ≥ p2 ≥ …` les probabilités triées et `n` le
nombre d'options.

| colonne | définition | sens |
|---|---|---|
| `margin_top2` | `p1 - p2` | ↑ = plus certain |
| `entropy_norm` | `-Σ pᵢ log pᵢ / log n` | ↑ = **moins** certain |
| `ratio_top2` | `p1 / max(p2, 0.005)` | ↑ = plus certain |

Conventions, et pourquoi :

- **`entropy_norm` varie en sens inverse des deux autres.** Pour les courbes
  risk–coverage, seuiller sur `1 - entropy_norm` ou inverser le sens de
  comparaison. C'est la source d'erreur la plus probable de `analyze.py`.
- `0 · log 0 = 0` par convention. Normalisation par `log n` : `entropy_norm`
  vaut 1 sur la distribution uniforme, quel que soit le nombre d'options,
  ce qui rend deux questions de tailles différentes comparables.
- **`ratio_top2` quand `p2 = 0`** : le rapport est non borné. On plancherise
  `p2` à **0,005**. L'API renvoie des probabilités arrondies au centième
  (observé sur nos appels, cohérent avec les exemples de la documentation) :
  un `0.00` affiché signifie donc « inférieur à 0,005 », et 0,005 est le
  milieu de l'intervalle qui s'arrondit à zéro. Le plancher est une
  conséquence de la quantification de l'API, pas une hypothèse de modèle.
  Conséquence à ne pas oublier : `ratio_top2` sature à **200** et ne
  discrimine plus du tout à l'intérieur de l'ensemble saturé — ce qui pèsera
  sur son pouvoir discriminant en haut de l'échelle.

Ces trois quantités sont entièrement dérivables de `probabilities`, qui est
stocké. Les écrire dans le JSONL est une commodité, pas une source de vérité :
en cas de doute sur une définition, elles sont recalculables depuis la colonne
brute sans refaire un seul appel.

Implémentation de référence, à reprendre telle quelle dans les deux runners :

```python
import math

def descriptive_stats(probabilities: dict[str, float]) -> dict[str, float]:
    ps = sorted(probabilities.values(), reverse=True)
    p1, p2 = ps[0], ps[1]
    n = len(ps)
    entropy = -sum(p * math.log(p) for p in ps if p > 0)
    return {
        "margin_top2": p1 - p2,
        "entropy_norm": entropy / math.log(n),
        "ratio_top2": p1 / max(p2, 0.005),
    }
```

## Hypothèse à tester, et non résultat

Sur les trois réponses obtenues via `probe.py`, deux questions portant sur le
même énoncé ambigu ont renvoyé `confidence = 0.18` malgré des distributions
très différentes :

- 2 options — `{shipping: 0.41, billing: 0.59}` → `confidence = 0.18`
- 4 options — `{other: 0.38, billing: 0.33, returns: 0.23, shipping: 0.06}`
  → `confidence = 0.18`

Sur la question à 2 options, 0,18 vaut exactement `p1 - p2`. Sur celle à 4
options, l'écart top-2 vaut 0,05 : `confidence` n'est donc pas un simple
margin top-2.

**Cela ne démontre rien.** Trois observations sur deux énoncés ne permettent
ni de caractériser la statistique employée par l'API, ni d'affirmer qu'une des
trois colonnes alternatives sépare mieux les bonnes des mauvaises réponses.
L'hypothèse — *`margin_top2`, `entropy_norm` ou `ratio_top2` pourraient avoir
un pouvoir discriminant supérieur à `confidence` pour décider quand escalader* —
est ouverte. Elle sera tranchée sur les 500 exemples, en comparant les quatre
colonnes sur les mêmes courbes risk–coverage, et pas avant.

## Dataset

500 exemples du split test de Banking77, graine 42. Provenance, licence et
empreintes : `data/README.md`.
