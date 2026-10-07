# Grimperoots Indexer

Ce dépôt exporte les articles et les tags du site Joomla 6 Grimperoots. L’assistant analyse les comptes rendus à partir des fichiers locaux et enregistre les propositions dans `data/proposals.json`. Après autorisation du lot, les tags retenus sont appliqués avec l’API Joomla.

## État du projet

- Les exports Joomla, le référentiel des tags et les propositions sont dans `data/`, ignoré par Git.
- `TAGS.md` décrit les tags disponibles et leurs règles métier.
- L’analyse sémantique est faite dans la conversation à partir du texte complet exporté ; aucune clé ni dépendance de classification externe n’est nécessaire.
- `apply.py <ID>` inspecte une proposition ; `apply.py --all` parcourt toutes les propositions validées. Sans `--apply`, les commandes simulent les changements.

## Prérequis et configuration

- Python 3.10 ou supérieur.
- Un accès API Joomla pour actualiser les exports et appliquer les tags.
- `.env.local` à la racine du dépôt, ignoré par Git :

```dotenv
JOOMLA_BASE_URL=https://www.example.org/j6
JOOMLA_TOKEN=jeton-joomla
```

## Actualiser les exports Joomla

```bash
python3 fetch_tags.py
python3 fetch_categories.py
python3 fetch_authors.py
python3 fetch_articles.py
```

Les scripts exportent vers `data/tags.json`, `data/categories.json`, `data/authors.json` et `data/articles.json`. Ils utilisent l’API Joomla en lecture seule.

## Faire analyser des articles

Demande à l’assistant d’analyser un ou plusieurs IDs à partir des exports de `data/`. Il lit l’article en entier, vérifie la catégorie, les tags existants et `TAGS.md`, puis présente un diff `+Tag` / `-Tag` avec une justification concise. Il enregistre les propositions en attente (`review.status=pending`) dans `data/proposals.json`. Les tags existants sont conservés ; tout retrait doit être explicitement demandé ou validé.

Une fois le diff du lot examiné, autorise explicitement son application. L’assistant marque alors les propositions retenues comme validées (`review.status=validated`) et renseigne les tags finaux. Les tags autorisés viennent de l’export Joomla ; un nouveau tag doit d’abord être créé dans Joomla, puis son export et `TAGS.md` doivent être actualisés avant de pouvoir l’ajouter à une proposition.

Les exports et propositions sont locaux et ignorés par Git. Ils ne modifient pas Joomla.

## Appliquer les propositions

Commence par inspecter le lot :

```bash
python3 apply.py --all --dry-run
```

Après autorisation explicite, appliquer les propositions validées :

```bash
python3 apply.py --all --apply
```

Pour un seul article :

```bash
python3 apply.py 764 --dry-run
python3 apply.py 764 --apply
```

Sans `--apply`, aucune écriture n’est envoyée. Le script compare les tags Joomla à l’état de départ de la proposition, vérifie les retraits approuvés, affiche les différences `+Tag (ID)` / `-Tag (ID)`, puis relit chaque article après PATCH. En cas de réponse HTTP 500, la relecture détermine si les tags ont tout de même été enregistrés ; les états inconnus ou inattendus restent des erreurs.

Sur l’instance actuelle, JComments provoque une réponse HTTP 500 après certains PATCH. Voir [BUGS.md](BUGS.md). Les journaux sont écrits dans `logs/`, ignoré par Git.

La qualité des associations pourra être revue après application et corrigée dans un lot ultérieur.

## Rendu HTML

Pour générer le HTML d’un article exporté :

```bash
python3 render_article.py 802
```

Le fichier est écrit dans `output/`.
