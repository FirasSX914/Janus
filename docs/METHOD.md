# Méthode

## Contrat du JSONL de run

Une ligne par exemple. `run_jev.py` et `run_frontier.py` écrivent ces colonnes,
dans cet ordre :

```
id, text, gold_label, model_id, prediction, confidence, probabilities,
margin_top2, entropy_norm, ratio_top2,
input_tokens, latency_ms, prompt_hash, run_date
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
L'API ne renvoie pas les clés dans l'ordre où les options ont été envoyées, et
cet ordre varie d'une réponse à l'autre : `analyze.py` ne doit jamais s'appuyer
dessus, seulement sur les noms.

`run_date` est un timestamp UTC ISO-8601 pris au moment de l'appel, suffixé `Z`.

## Le protocole de questionnement

Une question `Choice` par exemple, à **exactement 77 options**, une par label du
dataset. Instructions et critères viennent de `src/labels.py`, importé à
l'identique par les deux runners. Ni l'ordre des options ni la formulation des
critères ne doivent différer entre `run_jev.py` et `run_frontier.py` : c'est le
point de rupture le plus probable de la comparaison, parce qu'il produirait un
écart de performance imputable au prompt et non aux modèles. Un seul module
partagé rend la divergence impossible sans édition délibérée, et tout changement
déplace le `prompt_hash` des deux runs.

### Pas d'option `other`

La documentation TypeSafe recommande d'ajouter une option `other` ou
`none of the above` quand la liste risque de ne pas couvrir l'entrée. Ce n'est
pas le cas ici et l'option est délibérément absente.

Banking77 est un problème **fermé** : les 77 labels couvrent le dataset par
construction et chaque exemple a exactement un gold parmi eux. Une 78ᵉ option ne
pourrait donc jamais être correcte. La choisir serait toujours une erreur, et
mesurer sa fréquence reviendrait à mesurer la propension de Jev à s'échapper,
pas sa capacité à trancher — ce qui n'est pas la question posée.

Elle fausserait en plus `entropy_norm`, dont le dénominateur est `log(n)` : avec
78 options au lieu de 77, l'entropie normalisée de deux runs ne serait plus
comparable.

### `prompt_hash`

`prompt_hash` est le SHA-256 de la partie **constante** du prompt, pas du prompt
complet. Entrent exactement dans le hash :

```python
PROMPT_CONSTANT = {"instructions": INSTRUCTIONS, "criteria": CRITERIA}
PROMPT_HASH = hashlib.sha256(
    json.dumps(PROMPT_CONSTANT, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
).hexdigest()
```

- `INSTRUCTIONS` : la chaîne d'instructions de la question.
- `CRITERIA` : les 77 couples nom → description, **dans l'ordre d'envoi**, qui est
  celui des ids du dataset. Pas de `sort_keys` : réordonner les options change le
  corps de la requête, donc doit changer le hash.
- Sérialisation JSON compacte (`separators=(",", ":")`), sans échappement ASCII,
  encodée en UTF-8.

N'entre **pas** dans le hash : le `state`, qui change à chaque exemple. L'y
inclure donnerait un hash unique par ligne, incapable de détecter ce pour quoi il
existe — un changement de protocole en cours de run. N'entrent pas non plus le
nom du modèle ni les paramètres client, qui ont leurs propres colonnes.

Avant toute reprise, `run_jev.py` vérifie le `prompt_hash` de chaque ligne déjà
présente et refuse de continuer s'il diffère du prompt courant, plutôt que de
laisser deux versions de prompt cohabiter dans un même fichier.

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
  `p2` à **0,005**, moitié du pas de la grille mesurée ci-dessous. Un `0.00`
  renvoyé signifie « sous le pas de la grille », et 0,005 en est le milieu.
  Le plancher est une conséquence de la discrétisation de l'API, pas une
  hypothèse de modèle. Conséquence à ne pas oublier : `ratio_top2` sature à
  **200**.

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
    # + 0.0 : sans lui une distribution saturée donne -0.0 au lieu de 0.0
    entropy = -sum(p * math.log(p) for p in ps if p > 0) + 0.0
    return {
        "margin_top2": p1 - p2,
        "entropy_norm": entropy / math.log(n),
        "ratio_top2": p1 / max(p2, 0.005),
    }
```

## Contrainte expérimentale : la variable de confiance est discrète

Fait mesuré avant le run, sur le texte HTTP brut (`raw_http_response.text`),
donc avant tout parsing par le SDK :

- Sur **1 540 valeurs de probabilité** relevées, **aucune** ne sort de la grille
  du centième, et le maximum observé est de **2 décimales**. La discrétisation
  vient de l'API, pas du SDK.
- **`confidence` a la même granularité que `probabilities`** : pas de 0,01, pas
  plus fin.
- `Noul` renvoie également des valeurs au centième : la granularité est la même
  sur les trois primitives.

Deux conséquences directes, qui sont des propriétés de l'interface de sortie :

1. **Rien n'est représentable entre 0,99 et 1,00.** Toute valeur réelle dans cet
   intervalle est rapportée à l'une des deux bornes. On ne sait pas si l'API
   arrondit ou tronque — faute de valeur de référence, on ne peut pas trancher —
   mais dans les deux cas la résolution y est perdue.
2. **Le palier `1.00` est un atome.** Quand il est atteint, le vecteur de
   probabilités observé est `1.0` sur une option et `0.0` sur toutes les autres,
   identique d'un exemple à l'autre. Or `margin_top2`, `entropy_norm` et
   `ratio_top2` sont des fonctions de ce vecteur : sur cet atome elles prennent
   une valeur constante (`1.0`, `0.0`, `200.0`). Aucune statistique dérivée de
   `probabilities` ne peut donc départager deux exemples de cet atome, quelle
   qu'elle soit.

C'est une contrainte expérimentale sur ce qui est **mesurable**, et rien de plus.
Elle ne dit rien de l'utilité de Jev, ni de sa performance, ni de la pertinence
de la question posée. Elle dit à quelle finesse l'instrument gradue.

La variable de confiance exposée est en outre **fortement saturée** : une large
part des appels atteint le palier `1.00`. Cette concentration a été constatée sur
le diagnostic d'interface décrit ci-dessous ; sa valeur exacte sur le dataset
sera lue sur le run des 500.

### Compléments mesurés sur le run des 500

Deux faits relevés sur l'ensemble du run (38 500 valeurs de probabilité), que les
échantillons de diagnostic, plus petits, ne faisaient pas apparaître. Ils portent
sur l'interface de sortie, pas sur la performance.

- **La somme de `probabilities` ne vaut pas toujours 1.** 467 lignes sur 500
  somment à 1,00 et **33 somment à 0,99**. La masse manquante est un résidu
  d'arrondi réparti sur la grille du centième, pas la trace d'une option non
  listée : les clés sont toujours exactement les 77 labels envoyés.
  `analyze.py` ne doit donc **pas** poser `sum(probabilities) == 1` comme
  invariant, et doit tolérer 0,99.
- **44 valeurs sur 38 500 (0,11 %) s'écartent de la grille du centième**, d'au
  plus 1,11 × 10⁻¹⁶, soit un ULP de double. Elles ressemblent à un résidu calculé
  en virgule flottante côté serveur (`0.21000000000000002` plutôt que `0.21`).
  Ce n'est **pas** de la résolution supplémentaire : la granularité utile reste
  0,01. `analyze.py` arrondit au centième avant tout regroupement, sinon ces 44
  valeurs créeraient des niveaux de confiance fantômes.

### Diagnostic d'interface, sans valeur de performance

La granularité et la saturation ci-dessus ont été établies sur **20 exemples
tirés au hasard** hors dataset de rodage (graine 20260917), plus quelques appels
isolés. Ces appels documentent **l'interface de sortie de l'API** : quelles
valeurs elle sait représenter, et comment elles se répartissent.

**Ils ne mesurent aucune performance.** Aucun taux de bonnes réponses,
d'accuracy, de saturation ou d'erreur issu de ces 20 appels n'est reporté dans ce
document, ni ne doit l'être ailleurs : l'effectif est trop faible pour porter un
chiffre de performance, et les exemples n'ont pas été tirés pour cela. Les
sorties correspondantes vivent hors de `results/raw/` et ne sont pas commitées.
Tout chiffre de performance vient du run des 500, et de lui seul.

## Format de sortie de `analyze.py`

La variable de confiance étant discrète, les bandes interpolées n'ont pas lieu
d'être : elles inventeraient des points entre des valeurs que l'API ne sait pas
produire. `analyze.py` produit **une ligne par valeur de `confidence` réellement
observée** :

| Confidence | N | Correct | Accuracy |
|---|---|---|---|

Le palier **`1.00` est traité comme un atome** et n'est jamais subdivisé — ni par
`margin_top2`, ni par `entropy_norm`, ni par `ratio_top2`, qui y sont constants
par construction. Même chose pour le risk–coverage et la cascade : les points
sont les niveaux observables, pas un continuum de seuils.

La question du projet est inchangée : **à quels niveaux de confiance observables
peut-on déléguer à Jev en maintenant une accuracy cible ?**

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
colonnes sur les mêmes points observables, et pas avant.

Une restriction de portée, qui tient de la structure et non de l'observation :
les trois colonnes étant des fonctions de `probabilities`, elles sont constantes
sur l'atome `1.00` (voir la contrainte expérimentale ci-dessus). L'hypothèse
n'est donc testable que **hors de cet atome**. Sur l'atome lui-même, elle est
sans objet — non pas réfutée par les données, mais exclue par la forme de ce que
l'API renvoie.

## Dataset

500 exemples du split test de Banking77, graine 42. Provenance, licence et
empreintes : `data/README.md`.

### Pas d'analyse par classe sur ce run

Le tirage est uniforme et non stratifié : les 77 labels sont tous représentés,
mais avec **1 à 12 exemples chacun**. À ces effectifs, une accuracy par classe a
un intervalle de confiance plus large que l'écart qu'elle prétendrait mesurer, et
une courbe de calibration par classe n'a pas de sens sur une poignée de points.

On s'en tient donc à la **calibration globale** : calibration par niveau de
confiance observé, risk–coverage et cascade, toutes agrégées sur les 500. Aucune
conclusion par label ne sera tirée de ce run. Du per-class demanderait un tirage
stratifié — un autre fichier, une autre graine documentée, pas un redécoupage de
celui-ci.
