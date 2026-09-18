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
Chez un fournisseur à tarif horaire, c'est cette heure qui fixe le régime
tarifaire, donc elle est relevée **avant** l'appel et réutilisée pour le calcul
de coût.

Les fichiers frontier ajoutent des colonnes en fin de ligne, absentes du run Jev
dont la sortie n'est pas facturée : `output_tokens`, `cost_usd`, `pricing_tier`,
et selon le backend `cache_hit_tokens`, `cache_miss_tokens`, `reasoning_tokens`.
Voir « Le run frontier ».

## Le protocole de questionnement

Une question `Choice` par exemple, à **exactement autant d'options que la tâche a
de classes** — 77 pour Banking77, 145 pour WOS-46985 — une par label du dataset.
Instructions et critères viennent du module de labels de la tâche
(`src/labels.py`, `src/labels_wos.py`), importé à l'identique par les deux
runners via `src/tasks.py`. Ni l'ordre des options ni la formulation des critères
ne doivent différer entre `run_jev.py` et `run_frontier.py` : c'est le point de
rupture le plus probable de la comparaison, parce qu'il produirait un écart de
performance imputable au prompt et non aux modèles. Un seul module partagé rend
la divergence impossible sans édition délibérée, et tout changement déplace le
`prompt_hash` des deux runs de cette tâche.

Les runners ne connaissent aucun dataset : ils prennent `--task` et lisent dans
`tasks.py` le chemin des données, les instructions et les critères. Ajouter un
dataset est une entrée dans le registre plus deux fichiers, jamais une copie de
runner — ce qui évite qu'un correctif s'applique à l'un et pas à l'autre.

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
- `CRITERIA` : les couples nom → description de la tâche, **dans l'ordre
  d'envoi**, qui est celui des ids du dataset. Pas de `sort_keys` : réordonner les options change le
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

La comparaison se fait par **AUROC** — probabilité qu'une réponse juste reçoive
un score supérieur à une réponse fausse, les ex aequo comptant 1/2, ce qui est
indispensable sur une grille aussi grossière — et l'écart entre deux statistiques
est jugé par **bootstrap apparié** : à chaque tirage, le même jeu d'indices est
appliqué aux quatre scores, de sorte que les différences portent exactement sur
les mêmes observations. 10 000 itérations, graine 1729, intervalles en
percentiles. L'appariement supprime la variance d'échantillonnage commune aux
quatre statistiques ; comparer leurs intervalles marginaux, qui se recouvrent
largement, répondrait à une autre question et sous-estimerait la puissance du
test. Un intervalle de différence contenant zéro ne départage pas.

Une restriction de portée, qui tient de la structure et non de l'observation :
les trois colonnes étant des fonctions de `probabilities`, elles sont constantes
sur l'atome `1.00` (voir la contrainte expérimentale ci-dessus). L'hypothèse
n'est donc testable que **hors de cet atome**. Sur l'atome lui-même, elle est
sans objet — non pas réfutée par les données, mais exclue par la forme de ce que
l'API renvoie.

### Ce que le bootstrap a mesuré

Sur les 262 observations hors atome : **les données ne montrent pas
d'amélioration des statistiques alternatives par rapport à `confidence` ; deux
comparaisons donnent un avantage statistiquement détectable à `confidence`, de
faible amplitude** (+0,011 pour `margin_top2`, IC [+0,001, +0,021] ; +0,015 pour
`ratio_top2`, IC [+0,003, +0,028]). La troisième, `entropy_norm`, est
indiscernable de `confidence` (+0,002, IC [−0,012, +0,015]).

Formulé ainsi et pas autrement : les alternatives n'ont pas été pré-enregistrées
avec une marge minimale à battre. On constate donc **l'absence d'amélioration**,
on ne renverse pas l'hypothèse. Et un écart d'AUROC de l'ordre du centième, dont
la borne basse est à +0,001, ne désigne pas un vainqueur utilisable.

## Le run frontier

`run_frontier.py` ne connaît aucun fournisseur. Le backend est choisi par
`--provider` et vient de `src/providers.py`, qui expose une interface unique :

```python
call(state) -> Completion(prediction, input_tokens, output_tokens, model_id, extra)
```

Ajouter un backend est donc un module de plus, pas une réécriture du runner.
Tous reçoivent le **même énoncé**, construit dans `providers.py` à partir de
`labels.py` : mêmes 77 labels, même ordre, même formulation. Et tous contraignent
la sortie à l'enum des 77 labels — le mécanisme diffère par fournisseur, jamais
le contenu.

`prompt_hash` est calculé par la **même formule** que le runner Jev, sur la même
partie constante. Tous les fichiers de résultats doivent porter un `prompt_hash`
identique, et cette égalité est la preuve vérifiable que les modèles ont reçu le
même énoncé. Limite connue : le hash couvre les instructions et les 77 critères,
pas l'enveloppe de rendu propre à chaque fournisseur, laquelle ne fait qu'aplatir
ces mêmes données.

### Colonnes laissées nulles

Aucun modèle frontier testé **n'expose de distribution de probabilités
comparable** à celle de Jev. Les colonnes `confidence`, `probabilities`,
`margin_top2`, `entropy_norm` et `ratio_top2` sont donc `null` dans les fichiers
frontier. Elles ne sont ni fabriquées, ni approximées, ni dérivées d'une
auto-évaluation demandée au modèle : une confiance produite par un mécanisme
différent ne serait pas comparable, et la loger dans la même colonne inviterait
précisément à la comparer.

Conséquence : **aucune courbe de calibration ni de risk–coverage n'est traçable
pour un frontier.** Il entre dans la cascade comme un recours à accuracy et coût
fixes, pas comme un modèle qu'on pourrait à son tour seuiller.

## Procédure de rodage

Tout rodage se fait sur un **échantillon aléatoire à graine documentée**, tiré
dans les 500, et **jamais sur les premiers ids du fichier**. Le tirage porte sur
les 500 avant de retirer les ids déjà traités, de sorte que l'échantillon ne
dépende que de la graine et pas de l'avancement du run. `run_frontier.py` exige
`--sample` et `--seed` ensemble : un rodage sans graine n'est pas reproductible.

Cette règle vient d'un défaut constaté deux fois. Les deux premiers rodages
prenaient les 10 premiers ids du dataset. Or le dataset est trié par label
d'origine : **9 de ces 10 ids appartiennent à la même classe** (`card_arrival`),
la dixième à une classe voisine. Les deux rodages ont donc comparé les modèles
sur une seule classe facile, produit deux fois une égalité, et **n'étaient pas
informatifs** — ni sur l'accuracy, ni sur l'écart entre modèles. Le défaut était
dans la procédure, pas dans le signal.

Graines utilisées dans le projet, toutes distinctes pour qu'aucune confusion ne
soit possible :

| graine | usage |
|---|---|
| 42 | sous-échantillonnage des 500 exemples dans le split test |
| 20260917 | diagnostic d'interface de l'API TypeSafe (20 appels) |
| 1729 | bootstrap apparié des AUROC |
| 8191 | rodage aléatoire des backends frontier |

La graine **42** sert au sous-échantillonnage de *chaque* dataset, et **8191** au
rodage de *chaque* dataset : les graines sont attachées à un rôle, pas à un
dataset. Deux datasets différents tirés avec la même graine produisent des
échantillons différents, puisque la population diffère.

### Ce que le rodage sert à valider

Le rodage valide la **mécanique** : que le structured output contraigne
réellement aux 77 labels, que le tarif et la découpe du cache soient calculés
correctement, que la version du modèle soit celle attendue, que la latence soit
soutenable. Il ne sert **pas** à choisir un modèle sur son accuracy : dix
exemples ne mesurent aucune accuracy, et deux rodages l'ont déjà démontré par
l'absurde.

## Frontier baseline — v1

### Ce que la v1 cherche à établir

La question n'est pas « DeepSeek bat-il Jev ». C'est :

> **une cascade Jev → DeepSeek atteint-elle 90 %, 95 % ou 98 % d'accuracy à un
> coût inférieur à DeepSeek seul ?**

Une égalité d'accuracy entre les deux modèles ne répond donc pas à la question,
dans un sens ni dans l'autre. Ce qui compte est la structure des désaccords :
une cascade n'a d'intérêt que si le frontier rattrape des erreurs que Jev commet
là où Jev se déclare peu sûr, et le coût ne baisse que si Jev tranche seul une
part suffisante des cas. Les erreurs communes aux deux modèles ne sont
rattrapables par aucune cascade et fixent le plafond atteignable.

### Statut des fichiers de résultats

Trois statuts distincts, à ne pas confondre :

| fichier | statut | usage |
|---|---|---|
| Gemini 3.8 Flash, 7 lignes | **run abandonné** | **données exclues**, fichier supprimé, ne servent jamais |
| `deepseek_banking77_500.jsonl`, 20 premières lignes | **diagnostic pré-run** | valident la mécanique, ne fondent aucun résultat |
| `deepseek_banking77_500.jsonl`, une fois complet | **résultat expérimental** | seule source des chiffres publiés |

Les lignes de diagnostic DeepSeek restent dans le fichier, contrairement aux
lignes Gemini qui ont été supprimées. La différence n'est pas cosmétique : le run
DeepSeek est **en cours** et les 490 restantes le compléteront sous le même
`prompt_hash`, donc ces lignes seront des observations du run final au même titre
que les autres. Le run Gemini est **abandonné** : ses lignes n'auraient jamais
été complétées et ne pouvaient servir à rien.

### Le fournisseur écarté : Gemini 3.8 Flash

La baseline v1 a d'abord été tentée sur **Gemini 3.8 Flash**, via l'API Google AI
Studio. Elle est abandonnée, et ses données exclues.

- **Quota du tier gratuit observé : 20 requêtes par jour.** Constaté par le
  message de quota renvoyé par l'API elle-même —
  `Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 20, model: gemini-3.8-flash`.
  Le délai de reprise annoncé par l'API (« Please retry in ~15s ») s'est révélé
  trompeur : après six attentes successives des délais indiqués, soit environ six
  minutes, le 429 persistait. Un quota par minute se serait rouvert.
- **500 exemples demanderaient 25 jours.** Infaisable.
- Le rodage s'est arrêté à **7 exemples**, tous pris au début du dataset et
  **tous de la même classe** (`card_arrival`). Ils ne permettent aucune
  estimation d'accuracy et ne sont utilisés ni dans les résultats, ni dans les
  conclusions. Le fichier correspondant a été supprimé plutôt que commité :
  7 lignes d'une seule classe ne constituent pas un résultat.
- **Aucune conclusion comparative Jev vs Gemini n'est tirée**, dans aucun sens.
- Un **repli sur un modèle open-weight** (Groq, Cerebras, dont les tiers gratuits
  ne servent que `gpt-oss-120b` et `qwen-3.8-27b`) est écarté : la question posée
  est « payer un frontier vaut-il le coup », pas « un open-weight bat-il Jev ».
  Une cascade construite sur une autre question vaut moins que pas de cascade.
- **Faiblesse de reproductibilité à noter** : Gemini renvoie `model_id` égal à
  l'alias envoyé (`gemini-3.8-flash`), sans version résolue. Contrairement à
  `jev-1.13.0`, on ne peut pas savoir quelle version a répondu.

### Le backend retenu : DeepSeek V4-Pro

La baseline v1 est **DeepSeek V4-Pro** (`deepseek-v4-pro`), sur l'endpoint
compatible OpenAI.

**Contrainte aux 77 labels par tool call en mode strict.** C'est le seul
mécanisme réellement contraignant disponible, établi contre l'API et non
supposé : `response_format: {"type": "json_schema"}` est refusé (*« This
response_format type is unavailable now »*), et `json_object` ne garantit que du
JSON valide, pas l'appartenance à l'enum — il aurait fallu filtrer après coup, ce
qu'on s'interdit. Le mode strict impose le base_url `/beta`.

**`tool_choice` forcé est refusé en mode thinking** (*« Thinking mode does not
support this tool_choice »*). L'outil est donc proposé en `auto`. Si le modèle ne
l'appelle pas, le run **s'arrête** au lieu de rattraper la sortie autrement : une
prédiction qui échapperait à l'enum serait un défaut de protocole, pas une ligne
à réparer.

**Le mode thinking est actif par défaut et laissé tel quel.** C'est un **levier
non exploré**, pas un choix optimisé : ni `reasoning_effort` ni
`thinking: {type: ...}` ne sont passés. Les tokens de raisonnement sont
distinguables et logués dans `reasoning_tokens` ; ils sont déjà inclus dans
`completion_tokens`, donc dans `output_tokens`, et facturés au tarif de sortie.

**`model_id` est l'alias, pas une version résolue.** L'API renvoie
`deepseek-v4-pro` alors que la version annoncée est DeepSeek-V4-Pro-0813. Même
faiblesse de reproductibilité que Gemini, et à l'inverse de `jev-1.13.0` : on
loge ce que l'API renvoie, en sachant qu'il ne désigne pas une version figée.

### Coût : cache et heures pleines

Deux colonnes supplémentaires par rapport au run Jev, dont la sortie n'est pas
facturée : `output_tokens` et `cost_usd`. Et quatre propres à DeepSeek :
`cache_hit_tokens`, `cache_miss_tokens`, `reasoning_tokens`, `pricing_tier`.

**La découpe du cache n'est pas un détail.** Tarif officiel relevé le 2026-09-17
sur `https://api-docs.deepseek.com/quick_start/pricing`, en $ par million de
tokens :

| | cache hit | cache miss | sortie |
|---|---|---|---|
| heures creuses | 0,022 | 0,66 | 1,98 |
| heures pleines | 0,044 | 1,32 | 3,96 |

L'entrée en cache hit coûte **30 fois moins** qu'en miss. Nos 77 critères étant
constants sur les 500 appels, le préfixe est mis en cache et le taux de hit
mesuré au rodage dépasse 98 %. Un coût calculé sans distinguer les deux serait
faux d'un ordre de grandeur.

**Les heures pleines sont 01:00–04:00 et 06:00–10:00 UTC, du lundi au vendredi**,
au tarif exactement double. Le coût de chaque ligne est calculé au tarif de
**l'heure réelle de l'appel**, et `pricing_tier` consigne le régime appliqué pour
que le coût soit recalculable depuis la ligne seule.

### Claude Opus 5 — v2

Le run Opus 5 reste prévu, dès qu'un crédit API est disponible. Le protocole est
déjà figé et `AnthropicProvider` est en place : ce sera un
`--provider anthropic` à lancer, sans rouvrir le runner.

Deux points propres à ce backend, déjà inscrits dans le code. `temperature` en
est **absent par contrainte** : le paramètre est retiré de l'API sur cette
génération et une requête qui le contient renvoie une 400. Aucune
reproductibilité exacte ne sera donc revendiquée — la documentation officielle
précise par ailleurs que là où `temperature = 0` existait, il n'a jamais garanti
des sorties identiques. Et `fallbacks` n'est pas activé, à l'encontre de la
recommandation générale pour ce modèle : un repli servirait un autre modèle au
milieu du run, ce qu'un benchmark comparatif doit interdire.

## Cibles d'accuracy de la cascade

La cascade sera rapportée pour trois cibles d'accuracy : **90 %, 95 % et 98 %**.

Ces trois valeurs sont **fixées ici avant le moindre run frontier**, et avant
donc de connaître l'accuracy du modèle frontier, le coût de l'escalade et le
point de fonctionnement qui en résulte. La raison est simple : une cible choisie
après coup est toujours celle que les chiffres flattent, et un seuil ajusté sur
son propre résultat ne mesure plus rien. Elles ne seront pas révisées à la
lecture des résultats ; si l'une d'elles s'avère inatteignable, c'est ce constat
qui sera rapporté, pas une cible plus clémente.

### Les trois cibles sont inatteignables, et c'est un défaut de conception

Constat après le run frontier : **DeepSeek V4-Pro seul atteint 78,8 %** sur ce
dataset. Les trois cibles pré-enregistrées — 90 %, 95 %, 98 % — étaient donc
**hors de portée du fallback lui-même**, indépendamment de toute règle de
routage. Aucune cascade ne peut dépasser ce que son recours sait faire sur les
cas qu'on lui envoie.

C'est un **défaut de conception du protocole**, rapporté tel quel. Les cibles ont
été fixées sans borne supérieure connue : on savait Jev à 77,8 %, on ignorait ce
que vaudrait le fallback, et on a choisi des paliers ronds plutôt que des paliers
informés par une borne. Il aurait fallu, au minimum, conditionner les cibles à
l'accuracy du fallback une fois celle-ci mesurée — ce qui n'aurait pas été du
*post-hoc*, puisque la mesure du fallback précède la cascade.

**Les cibles ne sont pas révisées.** Elles sont rapportées `unattainable`, avec
le meilleur seuil effectivement atteint. Les remplacer maintenant par des valeurs
que les chiffres peuvent honorer reviendrait exactement à ce que la
pré-enregistrement devait empêcher.

### Le test qui reste, et son plafond

La question réellement décidable par ces données devient :

> **la cascade dépasse-t-elle 78,8 % — l'accuracy du fallback seul — pour moins
> de 0,220684 $, le coût du fallback seul ?**

C'est une comparaison à deux dimensions contre une référence unique et mesurée,
pas contre une cible arbitraire.

Le plafond de cette cascade est l'**oracle à 83,2 %** : sur 84 exemples des 500,
ni Jev ni DeepSeek ne produit la bonne réponse, donc aucune règle de routage
entre ces deux modèles ne peut les récupérer. Ce plafond est **propre au couple
Jev / DeepSeek V4-Pro**, pas une propriété du dataset ni de la méthode : un autre
fallback corrigerait peut-être une partie de ces 84 erreurs communes, et
déplacerait l'oracle d'autant. Le run Opus 5 prévu en v2 mesurera un oracle
différent.

## Second dataset : ce qui est écrit avant de lancer

Le protocole ne change pas. Même pipeline, mêmes métriques, mêmes garde-fous,
**mêmes cibles pré-enregistrées** — y compris les 90 / 95 / 98 % dont on sait
déjà qu'elles étaient mal conçues sur Banking77. Seul le dataset change.

### Le seuil 0,67 n'est pas un point de départ

**Si le seuil optimal du second dataset ne ressort pas proche de 0,67, ce n'est
pas un échec : c'est un résultat.** Il établirait que le seuil n'est pas
transférable d'une charge de travail à l'autre et doit être mesuré sur chacune —
ce qui est une conclusion utilisable, et déjà annoncée comme limite dans le
README de Banking77.

Le 0,67 reste un résultat de Banking77. Il ne sert ni de valeur par défaut, ni de
point de départ d'une recherche, ni de référence à retrouver. Le balayage du
second dataset est conduit à l'identique, sur tous les niveaux observés, et le
seuil qui en sort est lu tel quel.

Symétriquement : si la cascade ne dépasse pas le fallback seul sur ce dataset,
c'est rapporté ainsi. Un résultat négatif se publie exactement comme un positif,
et rien n'est réajusté après avoir vu les chiffres.

### Le dataset retenu : Web of Science WOS-46985

> This experiment uses the internally consistent (Domain, area) taxonomy from the
> dataset metadata (145 classes), rather than Y.txt's 134-class index mapping,
> because the latter cannot be mapped unambiguously to class names. Published
> WOS-46985 benchmark figures therefore are not treated as directly comparable
> external baselines.

Les faits qui imposent ce choix, relevés dans l'archive elle-même :

- **Les trois systèmes de labels de l'archive se contredisent** : `Y.txt` donne
  134 classes, les couples `(YL1, YL2)` en donnent 133, le `Meta-data` en donne
  145. Le `ReadMe.txt` annonce 134.
- **La correspondance indice → nom de `Y.txt` est ambiguë sur 10 valeurs.**
  `Y = 40` correspond à la fois à `Medical/Depression` et `Psychology/Depression` ;
  `Y = 71` correspond à trois classes `Civil` distinctes. Sans noms lisibles, pas
  de prompt possible.
- **`Depression` et `Schizophrenia` existent sous deux domaines**, ce qui impose
  le couple `Domain/area` comme clé : l'aire seule n'identifie pas une classe.
- **Effectifs très inégaux** : de 1 à 750 exemples par classe, médiane 359. Sur
  un tirage uniforme de 500 on attend ~3,4 exemples par classe contre 6,5 pour
  Banking77, donc la plupart des classes rares sont absentes — 134 des 145
  classes apparaissent dans l'échantillon.
- **Licence double** : CC BY 4.0 sur Mendeley, plus une concession de type MIT
  dans le `ReadMe.txt` de l'archive, copyright Kamran Kowsari 2017.

Aucun filtrage n'est appliqué pour retomber sur les 134 canoniques. Retirer les
11 classes de moins de 50 exemples y suffirait exactement — et c'est précisément
pour cela qu'on ne le fait pas : choisir un seuil parce qu'il reproduit le
chiffre attendu est l'ajustement *post-hoc* que le protocole s'interdit.

La vérité terrain est **plus faible que celle de Banking77** : les catégories
viennent des métadonnées de publication, pas d'un annotateur ayant lu chaque
résumé. Détaillé dans `data/README.md`.

### Ventilation des erreurs par domaine parent

Ajout **spécifique à ce dataset**, pour la raison suivante : la taxonomie est
hiérarchique à 7 parents et beaucoup de classes sont quasi synonymes à
l'intérieur d'un même parent. Confondre `CS/Machine learning` avec
`CS/Algorithm design` n'est pas la même erreur que la confondre avec
`Medical/Psoriasis`.

`cascade.py` rapporte donc, sur les erreurs communes aux deux modèles, combien
restent **dans le même domaine parent** que le gold et combien **le traversent**,
avec la même ventilation sur l'ensemble des erreurs Jev comme référence.

C'est une métrique de plus, et elle sert exactement au même usage que les paires
`(gold, prediction)` sur Banking77 : **interpréter** les erreurs communes, en
particulier estimer la part imputable à l'ambiguïté de la taxonomie. Elle
**n'entre pas** dans la mesure du seuil, ni dans la table de cascade, ni dans la
calibration. Le protocole de mesure est inchangé.

### Le `prompt_hash` sera différent, et c'est normal

`prompt_hash` couvre les instructions et les critères des labels. Un dataset aux
labels différents produit donc **nécessairement un hash différent** de celui de
Banking77 (`5736ce18…`). Ce n'est pas une rupture de protocole : le hash garantit
qu'à l'intérieur d'un même fichier de résultats, toutes les lignes ont reçu le
même énoncé, et qu'un runner Jev et un runner frontier portant sur le même
dataset ont reçu le même. Il ne prétend pas être stable d'un dataset à l'autre.

La garantie reste donc la même sur chaque dataset : un seul `prompt_hash` par
fichier, et un `prompt_hash` identique entre le fichier Jev et le fichier
frontier du même dataset.

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

## ECE et Brier — ajout descriptif postérieur aux résultats

**Ces deux métriques ont été ajoutées après la publication des résultats.** Elles
ne modifient **aucun seuil, aucune décision et aucune conclusion** de
l'expérience : ni les tables de cascade, ni les seuils optimaux de 0,67 et 0,37,
ni les cibles pré-enregistrées, ni la comparaison entre les deux datasets. Le
protocole reste gelé. Elles sont là parce que ce sont les deux chiffres qu'un
lecteur venant de la littérature sur la calibration cherchera en premier, et
qu'il valait mieux les calculer que le laisser les estimer de tête.

Elles portent sur les sorties de Jev uniquement. Le frontier n'expose pas de
distribution, donc ni ECE ni Brier ne sont définis pour lui.

### ECE

Écart absolu entre confiance moyenne et accuracy, pondéré par l'effectif de
chaque groupe. Deux variantes sont rapportées.

**Par niveau observé**, la variante principale : chaque valeur distincte de
`confidence` forme son propre groupe. C'est exact ici, et cohérent avec le reste
du document — la variable est discrète sur une grille au centième, donc un
découpage en bandes de largeur fixe mélangerait des niveaux que l'API distingue
et en séparerait d'autres sur une frontière arbitraire.

**En dix bandes égales**, la variante conventionnelle, rapportée uniquement pour
qu'un lecteur puisse comparer à des chiffres publiés ailleurs. Elle est
systématiquement plus basse que la précédente sur nos données, ce qui est attendu :
regrouper des niveaux voisins compense partiellement leurs écarts.

### Brier

Brier multiclasse : pour chaque exemple, somme sur **toutes** les classes du carré
de l'écart entre la probabilité annoncée et la cible one-hot. Il vaut 0 quand
toute la masse est sur le gold et 2 quand elle est entièrement ailleurs.

Calculé sur `probabilities` **brut, sans renormalisation**, conformément à la
règle posée pour le contrat du JSONL : l'API renvoie des valeurs au centième et
une partie des lignes somme à 0,99. Renormaliser fabriquerait une distribution que
le modèle n'a pas produite, au prix d'une amélioration cosmétique du score.

### Intervalles

Bootstrap non paramétrique sur les exemples, 10 000 tirages, graine 1729 — la même
que le bootstrap apparié des AUROC, puisque c'est le même rôle. Intervalles en
percentiles.

### Valeurs mesurées

| | Banking77 | WOS-46985 |
|---|---|---|
| confiance moyenne annoncée | 90,7 % | 83,2 % |
| accuracy empirique | 77,8 % | 52,8 % |
| écart brut | +12,9 points | +30,4 points |
| ECE, par niveau observé | 0,1568 [0,1418, 0,2000] | 0,3217 [0,2989, 0,3729] |
| ECE, 10 bandes égales | 0,1302 [0,1015, 0,1636] | 0,3047 [0,2676, 0,3469] |
| Brier multiclasse | 0,3518 [0,2947, 0,4102] | 0,7491 [0,6790, 0,8178] |

La réserve déjà posée sur WOS s'applique ici aussi, et pèse plus lourd sur ces
métriques que sur l'accuracy : une part inconnue de l'écart de calibration tient à
l'ambiguïté des labels plutôt qu'à une surconfiance du modèle. Un exemple dont le
gold est `biochemistry/Southern blotting` et qui reçoit une masse importante sur
`biochemistry/Molecular biology` est compté comme une erreur pleine par le Brier.

## Related work

Jev est sorti le 2026-09-15. Ce qui suit recense ce qui est apparu autour depuis,
**vérifié le 2026-09-17 sur les dépôts eux-mêmes**, et rien d'autre. Chaque ligne
renvoie à un README ou à une issue que nous avons lus. Les dépôts évoluent vite :
ces constats sont datés, pas définitifs.

Deux mises en garde sur la portée de ce recensement. Il ne s'appuie que sur une
recherche par nom sur GitHub, donc il ne prétend pas être exhaustif, et **aucune
affirmation du type « personne n'a fait X » n'en est tirée** — nous n'avons pas
mené une recherche assez large pour la soutenir. Et nous n'avons pas réexécuté
les mesures citées : elles sont rapportées telles que les dépôts les publient.

### Réimplémentations open-source du pattern

| dépôt | ce que c'est | calibration exposée | mesures sur vérité terrain |
|---|---|---|---|
| [TheoLeeCJ/openjev](https://github.com/TheoLeeCJ/openjev) | reproduit le pattern d'interface, lit les probabilités d'options d'un modèle 4B local | aucune métrique de calibration au README ; il recommande seulement de « calibrate and validate on the workload where they will make decisions » | **oui** — balanced accuracy publiée sur WANLI (256 lignes) et sur un jeu de décisions rédigées (144 lignes) |
| [bnsd55/openjev](https://github.com/bnsd55/openjev) | JSON contraint en un passage batché sur Apple Silicon (MLX) ; framework, pas de modèle entraîné | **oui** — temperature scaling ajusté par minimisation de NLL, ECE rapportée avant/après : 0,0870 → 0,0773 à T = 1,7178 | 24 cas étiquetés donnant 72 décisions au niveau champ |
| [genai-craft/openvons](https://github.com/genai-craft/openvons) | couche de décision texte / vision / voix, avec gating sur la confiance | **oui, la plus complète** — temperature, isotonic, et métriques ECE / Brier / NLL / macro-F1 dans `openvons.core` | benchmarks référencés dans `docs/lm_benchmark.md` et suivants |
| [kw2828/OpenJev](https://github.com/kw2828/OpenJev) | playground de décision et expériences Doom ; baseline NumPy de 5 253 paramètres apprise par clonage comportemental | aucune — le README dit explicitement « Scores are uncalibrated and conditional on the supplied candidates » | données Doom synthétiques |
| [zhihz/openjev](https://github.com/zhihz/openjev) | « Local bilingual probability decisions… Independent research preview » | non vérifié en détail | non vérifié |

D'autres dépôts portant ce nom existent et apparaissent dans la recherche
(`mikesmullin/openjev`, `franknoh/OpenJev`, `inboxpraveen/OpenJev`,
`allay-team/openjev`) ; nous ne les avons pas examinés.

Un dépôt cité par la liste de travail, `AlexWortega/openjev`, **n'a pas pu être
vérifié** : 404 aux deux casses au 2026-09-17. Il n'est référencé
qu'indirectement, par la description de `mikesmullin/openjev` (« Local
reproduction of AlexWortega/openjev »). Nous n'en tirons rien.

### Frameworks de décision sans modèle propre

| dépôt | ce que c'est | calibration exposée | mesures sur vérité terrain |
|---|---|---|---|
| [aigodsend9-boop/specter-decision-engine](https://github.com/aigodsend9-boop/specter-decision-engine) | framework Python, version 0.3.0 au moment de la vérification ; **aucun modèle entraîné embarqué** (« Não há modelo treinado embarcado »), le backend local est un scoreur lexical déterministe | **oui** — temperature par minimisation de NLL, isotonic par PAV, et Brier / NLL / ECE avec bootstrap | l'API de calibration prend des enregistrements étiquetés ; aucune mesure publiée sur un dataset nommé n'a été vérifiée |
| [grishahq/decisionbridge](https://github.com/grishahq/decisionbridge) | transforme des LLM existants (OpenAI, Anthropic, OpenRouter, MLX local) en fonctions de décision | temperature calibration sur exemples étiquetés séparés ; ni ECE ni Brier ni NLL au README | l'évaluation fournie est décrite comme « a small, English-only, **AI-authored synthetic** pilot » |
| [dbobo4/local-llm-probabilistic-decision-engine](https://github.com/dbobo4/local-llm-probabilistic-decision-engine) | transforme un modèle causal en moteur de décision par scoring direct des candidats (`choice`, `boolean`, `rating`) | aucune métrique au README ; il avertit que « Calibration must be measured separately on representative labeled data » | benchmarks de routage et de vérification arithmétique, centrés accuracy |

### Intégrations agent et outillage

[browser-use/jev-ultrafast](https://github.com/browser-use/jev-ultrafast) fait
choisir à Jev une opération et un élément dans un espace d'actions indexé pour
piloter un navigateur. Il publie des mesures de temps de tâche — médiane 9,450 s
→ 7,092 s — et précise lui-même leur portée : « This is three repeats of one task
on one browser profile, not a general reliability benchmark ». Pas de
calibration.

Plusieurs intégrations d'outillage existent et ont été constatées sans être
examinées : `jev-mcp` sous plusieurs propriétaires (`jkudish`, `blakestone-x`,
`benballintyn`), `typesafe-mod` (`BeLazy167`), `jev-playwright-mcp` (`krw82`),
`jev-review` (`NiazMorshed2007`).

### Le travail le plus proche du nôtre

[hamakyo/jev-starter](https://github.com/hamakyo/jev-starter) vise la même couche
que nous : contrats de décision, seuils de politique, fallbacks et évaluation. Le
README annonce « Brier score, calibration error, coverage/risk across confidence
thresholds, AURC where meaningful » comme **métriques prévues**, et décrit une
comparaison « Jev-only, baseline judge, and Jev → fallback judge cascade on the
same labeled dataset ». Son
[issue #5](https://github.com/hamakyo/jev-starter/issues/5), « Build the
evaluation harness for calibration and selective automation », spécifie ECE et
Brier, un balayage de seuils exposant l'arbitrage coverage / risk, les cascades
avec fallback, et un horodatage des tarifs pour éviter les dérives de coût
silencieuses.

C'est donc un programme de travail très proche du nôtre, annoncé comme tel. Au
moment de la vérification, ces métriques sont présentées comme prévues plutôt que
publiées ; nous n'avons pas vérifié l'état d'avancement de l'issue.

### La méthodologie de référence de TypeSafe

TypeSafe publie ses propres workflow evals, dont la méthode est exposée sous
[*How we evaluate* → *Assume the harness is correct*](https://evals.typesafe.ai/).
Vérifié le 2026-09-17 sur la page elle-même — il n'existe pas d'ancre ni de page
de méthodologie distincte, les deux phrases citées sont dans cette sous-section.
Les labels de référence y sont
« generated via an average of the responses of GPT-6 Astra and Claude Fable 5.1,
both at high thinking », et la méthode déclarée est d'« assume that the code is
correct, and measure against the current smartest large models » plutôt que
d'optimiser pour une classification de vérité terrain — le billet d'annonce dit
de même « We don't optimize for a ground truth classification ».

> **TypeSafe's reference methodology evaluates agreement with its reference
> models, whereas Janus evaluates predictions against human-labelled ground
> truth.**

C'est un contraste de méthode, pas un reproche : les deux approches répondent à
des questions différentes et aucune ne remplace l'autre. Mesurer l'accord avec un
consensus de grands modèles répond à « ce modèle décide-t-il comme les plus gros
décideraient » ; mesurer contre des labels humains répond à « ce modèle a-t-il
raison ». Un dataset comme Banking77 a ses propres limites, dont l'ambiguïté de
certains labels, relevée plus haut sur les 84 erreurs communes.

Sur leur **position déclarée à l'égard des classements publics** : nous n'avons
trouvé aucune prise de position explicite sur les pages consultées — ni refus de
participer, ni justification formulée comme telle. Ils exposent la raison de
construire leur propre évaluation, pas une position sur les classements. Nous
n'en affirmons donc rien.

### Disponibilité de Jev sur le AI Gateway de Vercel

Vérifié le 2026-09-17 sur le
[changelog Vercel](https://vercel.com/changelog/typesafe-ai-jev-now-available-on-ai-gateway)
et sur la [page modèle](https://vercel.com/ai-gateway/models/jev) : Jev est
disponible sur le AI Gateway de Vercel, annoncé le **16 septembre 2026** — le
lendemain de sa sortie — sous l'identifiant exact **`typesafe-ai/jev`**.

Sans incidence sur ce dépôt, qui appelle l'API TypeSafe directement : passer par
une passerelle ajouterait une couche entre le modèle et la mesure, et le
`model_id` consigné ne serait plus celui que l'API du fournisseur renvoie.

### Notre contribution

> Our contribution is an empirical evaluation of confidence-based selective
> automation on a real ground-truth dataset, rather than another implementation
> of the decision layer itself.

Ce que cela implique concrètement, et qui découle du reste de ce document : le
protocole a été figé avant tout résultat, le dataset est commité avec ses
empreintes, les résultats bruts le sont aussi, et la granularité réelle de la
variable de confiance a été mesurée avant d'être interprétée. Nous n'ajoutons
aucune métrique ni aucune méthode de calibration après avoir pris connaissance
de ces travaux : le protocole reste gelé.
