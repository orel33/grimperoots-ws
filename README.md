# Grimperoots Indexer

Ce dépôt exporte les articles et les tags du site Joomla 6 Grimperoots. L’assistant analyse les comptes rendus à partir des fichiers locaux et enregistre les propositions dans `data/proposals.json`. Après autorisation du lot, les tags retenus sont appliqués avec l’API Joomla.

## État du projet

- Les exports Joomla, le référentiel des tags et les propositions sont dans `data/`, ignoré par Git.
- `TAGS.md` décrit les tags disponibles et leurs règles métier.
- L’analyse sémantique est faite dans la conversation à partir du texte complet exporté ; aucune clé ni dépendance de classification externe n’est nécessaire.
- `apply.py <ID>` inspecte une proposition `ready` ; `apply.py --all` traite uniquement les propositions `ready`. Sans `--apply`, les commandes simulent les changements.

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

Demande à l’assistant d’analyser un ou plusieurs IDs à partir des exports de `data/`. Il lit l’article en entier, vérifie la catégorie, les tags existants et `TAGS.md`, puis présente un diff `+Tag` / `-Tag` avec une justification concise. Chaque proposition contient l’état initial complet `existing_tags`, la cible complète `final_tags` et un `status`. Une suggestion de l’assistant commence en `pending`. Les retraits doivent être explicitement demandés ou validés.

Quand tu valides une suggestion ou donnes explicitement la cible souhaitée, la proposition passe à `ready`. Les tags autorisés viennent de l’export Joomla ; un nouveau tag doit d’abord être créé dans Joomla, puis son export et `TAGS.md` doivent être actualisés avant de pouvoir l’ajouter à une proposition.

Format d'une entrée dans `data/proposals.json` :

```json
"710": {
  "existing_tags": [26, 28, 30, 31, 33, 35],
  "final_tags": [30, 33, 35],
  "status": "ready",
  "notes": "Course & Trail, Escalade et Mobilité Douce ne sont pas représentatifs."
}
```

`final_tags` est la liste complète envoyée dans le PATCH ; les ajouts et retraits se calculent par différence avec `existing_tags`. `notes` est facultatif et sert à garder le raisonnement.

Les exports et propositions sont locaux et ignorés par Git. Ils ne modifient pas Joomla.

## Démarrer un nouveau cycle de propositions

Avant un nouveau cycle, actualise les articles et les tags depuis Joomla, puis archive les décisions du cycle précédent :

```bash
python3 fetch_articles.py
python3 fetch_tags.py
python3 init_proposals.py
```

`init_proposals.py` archive le fichier existant dans `data/archive/proposals-<horodatage>.json` puis crée `data/proposals.json` avec `{}`. Le nouveau fichier se remplit uniquement avec les articles analysés pendant le cycle. Les tags courants de tous les articles restent disponibles dans `data/articles.json` ; ils n'ont pas à être dupliqués dans les propositions. La commande ne contacte pas Joomla. Si le fichier est déjà vide, elle le laisse tel quel et ne crée pas d'archive vide.

## Appliquer les propositions

Commence par inspecter le lot :

```bash
python3 apply.py --all --dry-run
```

Après avoir passé les propositions approuvées au statut `ready`, appliquer le lot :

```bash
python3 apply.py --all --apply
```

Pour un seul article :

```bash
python3 apply.py 764 --dry-run
python3 apply.py 764 --apply
```

Sans `--apply`, aucune écriture n’est envoyée. Le script compare les tags Joomla à `existing_tags`, affiche les différences `+Tag (ID)` / `-Tag (ID)`, puis relit chaque article après PATCH. En cas de réponse HTTP 500, la relecture détermine si la cible a tout de même été enregistrée ; les états inconnus ou inattendus restent des erreurs. `--all` ignore les propositions `pending` et `applied`.

Après relecture Joomla confirmant `final_tags`, `apply.py --apply` remplace `status: "ready"` par `status: "applied"`. Si l’article correspond déjà à la cible, il est également marqué `applied` sans PATCH. Le mode `--dry-run` ne modifie ni Joomla ni `proposals.json`. Les journaux dans `logs/` conservent l’heure, l’état avant/après, le résultat et les notes. Pour réviser un article appliqué, actualise `existing_tags` depuis Joomla, définis une nouvelle `final_tags` complète et remets son statut à `pending` ou `ready` selon que la cible attend encore une validation.

Un cycle peut rester dans `proposals.json` pour conserver ses décisions et ses statuts. Pour repartir sur une nouvelle campagne, utilise `init_proposals.py` : l'archive conserve l'historique et le nouveau fichier ne contient que les propositions du cycle à venir. Joomla reste la source de vérité pour les tags actuels.

Par défaut, `--apply` désactive temporairement par l’API Joomla le plugin **Content - Comments (JComments)**, ID 10005, pour toute l’exécution, puis le réactive s’il était actif au départ. Ce contournement évite le callback qui provoque HTTP 500 et peut laisser des articles verrouillés. `--keep-jcomments-enabled` permet de désactiver ce contournement. Les verrous déjà laissés par une exécution précédente doivent être check-in dans l’administration Joomla avant de retenter ces articles.

Le corps du PATCH contient uniquement l’ID de l’article et la liste finale des IDs de tags, sous la forme `{"id": 764, "tags": [33, 36]}`. Le script ne renvoie pas le titre, le texte, les images ni les autres champs de l’article. Les réponses GET servent à comparer l’état initial et à vérifier les tags après le PATCH ; elles ne sont pas renvoyées à Joomla. Cette écriture limitée aux tags réduit fortement le risque d’écraser ou d’endommager le contenu des articles.

Sur l’instance actuelle, JComments provoque une réponse HTTP 500 après certains PATCH et peut laisser l’article verrouillé par l’utilisateur API. Voir [BUGS.md](BUGS.md). Les journaux sont écrits dans `logs/`, ignoré par Git.

La qualité des associations pourra être revue après application et corrigée dans un lot ultérieur.

## Rendu HTML

Pour générer le HTML d’un article exporté :

```bash
python3 render_article.py 802
```

Le fichier est écrit dans `output/`.
