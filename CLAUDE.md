# calibre

Mesure la calibration de modèles de décision (Jev, TypeSafe AI) et simule des cascades Jev → frontier.

## Objectif

Répondre à : **à quel seuil de confiance peut-on laisser Jev décider plutôt que payer un modèle frontier, pour une accuracy cible donnée ?**

## Règles

- Run et analyse sont **séparés**. `analyze.py` et `cascade.py` ne font JAMAIS d'appel API : ils lisent uniquement les JSONL de `results/raw/`.
- Toute sortie de run est un JSONL, une ligne par exemple, colonnes exactes :
  `id, input, gold, predicted, confidence, probabilities, margin_top2, entropy_norm,
  ratio_top2, latency_ms, input_tokens, model_id, prompt_hash, run_date`
  `model_id` est la version résolue renvoyée par l'API, pas l'alias envoyé.
  Définitions des trois statistiques descriptives : `docs/METHOD.md`.
- Clés API dans `.env`, jamais en dur. `.env` est dans `.gitignore`.
- Pas de pandas, pas de framework, pas de notebook. `numpy` + `matplotlib` uniquement.
- Le dataset figé (500 exemples, seed fixé) est commité dans `data/`.
- Les résultats bruts sont commités dans `results/raw/`.

## API TypeSafe

Documentation : https://docs.typesafe.ai/llms.txt

**NE PAS deviner la signature du SDK.** L'API a moins d'une semaine, elle n'est dans les poids d'aucun modèle. Lire la doc avant d'écrire du code qui l'appelle.

Trois primitives :
- `Choice` — choisir une option dans une liste → `choice`, `probabilities`, `confidence`
- `Score` — noter sur un barème ordonné → `score`, `probabilities`, `confidence`
- `Noul` — probabilité qu'un énoncé soit vrai → `noul` (0–1)

**`Noul` ne renvoie PAS de champ `confidence`.** Choice et Score oui. Tout code qui suppose `answer.confidence` partout casse sur les binaires.

`confidence` n'est pas une probabilité d'avoir raison : c'est une statistique dérivée de la forme de la distribution. Ne jamais supposer que 0,9 = 90% de justesse — c'est précisément ce que ce projet mesure.

## Structure

```
src/
  probe.py        # un seul appel, imprime la réponse brute
  run_jev.py      # Jev sur le dataset → JSONL
  run_frontier.py # Opus 5 sur le dataset → JSONL
  analyze.py      # JSONL → calibration + risk-coverage + graphes
  cascade.py      # simulation cascade, zéro appel API
data/             # dataset figé
results/raw/      # JSONL de sortie
docs/             # METHOD.md, REPRODUCE.md
```

## Métriques produites

- accuracy globale (Jev et frontier)
- **courbe de calibration** : confiance annoncée vs accuracy empirique, 10 bandes
- **risk–coverage** : pour chaque seuil de 0,50 à 0,99 → couverture, accuracy, taux d'erreur
- **cascade** : pour chaque seuil → part traitée par Jev, part escaladée, accuracy finale, coût total
