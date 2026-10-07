# TODO.md — Grimperoots Indexer

## Phase 1 — Initialisation du projet

- [x] Initialiser le dépôt Git.
- [x] Créer ou compléter `AGENTS.md`.
- [x] Créer `.gitignore`.
- [x] Ignorer au minimum :
  - `.env`
  - fichiers contenant des tokens ;
  - caches Python et données locales (`data/`) ;
  - éventuels fichiers temporaires.
- [x] Ajouter une documentation d'utilisation dans `README.md`.
- [ ] Compléter l'arborescence cible (`src/`, `logs/`, etc.) si le projet en a besoin :

```text
grimperoots-indexer/
├── AGENTS.md
├── TODO.md
├── TAGS.md
├── README.md
├── src/
├── data/
└── logs/
```

---

## Phase 2 — Accès API Joomla

- [x] Vérifier les endpoints Joomla 6 utilisés (tags, catégories, utilisateurs et article individuel).
- [x] Mettre en place l'authentification par token.
- [x] Lire le token depuis `JOOMLA_TOKEN` (environnement, `.env` ou `.env.local`).
- [x] Ne jamais versionner le token ; les fichiers `.env*` sont ignorés.
- [x] Tester la récupération des tags.
- [x] Tester la récupération de la liste des articles (684 articles récupérés).
- [x] Tester la récupération d'un article précis (article 22).
- [x] Implémenter la pagination pour les exports de tags, catégories, auteurs et articles.
- [x] Vérifier la pagination avec une collection qui dépasse la limite d'une page (export de 684 articles).
- [x] Tester la récupération des catégories et des auteurs.

Endpoints à tester :

```text
GET /api/index.php/v1/tags
GET /api/index.php/v1/content/articles
GET /api/index.php/v1/content/articles/{id}
```

---

## Phase 3 — Export local

Un script d'export global reste à créer pour orchestrer ces commandes :

```bash
python export.py
```

Il doit :

- [x] récupérer tous les tags (`fetch_tags.py`) ;
- [x] récupérer tous les articles (`fetch_articles.py`) ;
- [x] sauvegarder les tags dans `data/tags.json` ;
- [x] sauvegarder les ressources Joomla complètes (texte et relations inclus) dans `data/articles.json` ;
- [x] rendre un article HTML à la demande depuis `data/articles.json` (`python render_article.py 22`).

`fetch_articles.py` conserve toutes les ressources d'articles dans `data/articles.json`. `render_article.py <id>` sélectionne une ressource dans ce fichier et génère `output/<id>.html`. Exports complémentaires : `fetch_categories.py` produit `data/categories.json` et `fetch_authors.py` produit `data/authors.json` (ID et nom uniquement).

Structure cible :

```text
data/
├── articles.json
├── authors.json
├── categories.json
└── tags.json
```

`articles.json` contient la liste `data` des ressources Joomla complètes, avec les relations d'auteur, de catégorie et de tags. Le renderer sélectionne l'article par ID sans créer de fichier JSON individuel.

Les informations essentielles disponibles par article incluent au minimum :

```json
{
  "id": 123,
  "title": "...",
  "alias": "...",
  "category": "...",
  "created": "...",
  "introtext": "...",
  "fulltext": "...",
  "existing_tags": []
}
```

- [x] Vérifier que les tags existants sont bien récupérés sur l'article individuel.
- [x] Ne pas télécharger les images pendant les exports ; conserver les références distantes de Joomla.

---

## Phase 4 — Documentation de la taxonomie

`TAGS.md` contient les IDs et intitulés exportés de Joomla ainsi qu'une première proposition de définitions métier. Ces définitions restent à valider avant d'être considérées comme référence.

Pour chaque tag :
- [x] nom et identifiant Joomla ;
- [x] première définition, cas d'utilisation et cas d'exclusion proposés ;
- [ ] validation métier des descriptions et arbitrage des périmètres signalés.

Exemple :

```markdown
## Corse

Utiliser lorsque la sortie décrite dans l'article se déroule réellement en Corse.

Ne pas utiliser pour une simple mention de la Corse.
```

---

## Phase 5 — Analyse des articles par l’assistant

L’analyse est effectuée dans la conversation à partir des exports locaux. L’utilisateur demande un article ou un lot d’IDs ; l’assistant lit le texte complet de chaque article dans `data/articles.json`, les tags existants dans `data/tags.json` et les règles de `TAGS.md`.

L’analyse est sémantique : identifier l’activité et le lieu réels, utiliser la catégorie comme indice, ignorer les mentions incidentes et ne sélectionner que des tags présents dans l’export Joomla. L’assistant présente un diff compact et une justification concise.

- [x] lire les articles complets depuis les exports locaux ;
- [x] utiliser les règles métier dans `AGENTS.md` et `TAGS.md` ;
- [ ] étendre progressivement l’échantillon analysé.

---

## Phase 6 — Propositions JSON

Après analyse, l’assistant ajoute ou met à jour les entrées correspondantes dans `data/proposals.json` avec `review.status=pending`. Ce fichier reste local et ignoré par Git. Il conserve pour chaque article les tags de départ, les tags proposés, les incertitudes et, après autorisation du lot, les tags finaux et les suppressions explicitement acceptées.

Exemple simplifié :

```json
{
  "802": {
    "title": "Compte rendu de sortie",
    "existing_tags": [20, 21],
    "suggested_tags": [33],
    "new_tags": [33],
    "uncertain_tags": [],
    "review": {
      "status": "pending"
    }
  }
}
```

- [x] distinguer tags existants, ajouts, incertitudes et retraits validés ;
- [x] ne jamais inventer un tag Joomla ;
- [x] conserver les tags existants par défaut ;
- [x] documenter les décisions après autorisation dans la proposition.

---

## Phase 7 — Revue et application par lot

L’assistant présente le résumé des changements avant application et enregistre les propositions en attente. L’utilisateur autorise explicitement le lot ; l’assistant marque les articles retenus `review.status=validated`, puis seuls ceux-ci sont traités par `apply.py`. Après application, une revue de qualité peut conduire à corriger les propositions et à envoyer un nouveau lot.

La création d’un tag reste manuelle dans Joomla. Après sa création, rafraîchir `data/tags.json`, documenter l’ID dans `TAGS.md`, puis l’ajouter aux propositions concernées.

---

## Phase 8 — Inspection et dry-run

`apply.py <ID>` inspecte un article et `apply.py --all` parcourt toutes les propositions validées, une par une. Les deux modes interrogent l'API Joomla en lecture seule par défaut, contrôlent la proposition et comparent ses tags à l'état courant. En mode global, les propositions non validées sont listées et ignorées ; une erreur sur un article est signalée sans interrompre les articles suivants.

```bash
python apply.py 764 --dry-run
python apply.py --all --dry-run
```

Affichage souhaité :

```text
[1/8] Article 764 — Les Segpa au ski de rando
  +Pyrénées (33)  -Randonnée (34)
  Simulation : aucun PATCH envoyé.
```

- [x] Pouvoir inspecter un article avec `python apply.py <ID> --dry-run`.
- [x] Parcourir toutes les propositions validées avec `python apply.py --all --dry-run`.
- [x] Afficher les changements avec un diff compact `+Tag` / `-Tag`.
- [x] Ignorer et lister les propositions qui n'ont pas été validées.
- [x] Ne faire aucune écriture en mode simulation (mode par défaut).
- [x] Refuser les propositions sans revue humaine validée et les suppressions non approuvées.
- [ ] Prévoir éventuellement une sortie CSV et l'inspection par tag.

---

## Phase 9 — Validation manuelle

État au 8 octobre 2026 : 18 comptes rendus ont fait l’objet d’une revue dans la conversation et leurs propositions ont été appliquées. Les articles ont été lus depuis les exports locaux. Une revue de qualité complémentaire après application reste prévue.

Pour la revue de qualité après application :

- [ ] contrôler un échantillon de 20 à 50 articles après application (18 articles discutés/validés à ce jour) ;
- [ ] vérifier plusieurs types de sorties ;
- [ ] vérifier les articles courts ;
- [ ] vérifier les articles contenant plusieurs lieux ;
- [ ] vérifier les mentions incidentes ;
- [ ] vérifier les articles avec plusieurs activités ;
- [ ] corriger les règles dans `AGENTS.md` ou `TAGS.md` si nécessaire ;
- [ ] corriger les règles ou propositions si la revue révèle des erreurs.

---

## Phase 10 — Écriture Joomla

Le 8 octobre 2026, `python apply.py --all --apply` a parcouru les 18 propositions validées. Neuf articles ont reçu de nouveaux tags ou des retraits validés ; les neuf autres étaient déjà conformes. Une relecture API a confirmé l’état cible pour chaque PATCH malgré la réponse HTTP 500. Le tag Joomla `Via Ferrata` (ID 42) a ensuite été exporté et ajouté au CR 600 par un PATCH ciblé, également confirmé par relecture. Les journaux d’application par article se trouvent dans `logs/`.

La cause du HTTP 500 reste le plugin de contenu `JComments` pendant `onContentAfterSave` : il appelle `Route::_()` dans le contexte API, ce qui aboutit à `Call to undefined method Joomla\CMS\Router\ApiRouter::build()`. Le manifeste installé indique JComments 5.0.6 et le journal Joomla indique Joomla 6.1.4. L’article et ses tags sont enregistrés avant cette erreur post-save ; `apply.py` affiche un avertissement, relit l’article et distingue une cible confirmée d’un état inconnu ou inattendu. Pour les prochaines écritures, conserver le dry-run et vérifier les journaux et les relectures ; corriger JComments reste souhaitable, mais n’est pas un prérequis pour les tags tant que les relectures confirment les résultats.
```bash
python apply.py 764 --apply
python apply.py --all --apply
```

- [x] utiliser l'API Joomla avec `PATCH` sur un article précis ;
- [x] appliquer plusieurs articles et confirmer les états finaux par relecture API ;
- [x] envoyer l'ensemble final des tags voulu ;
- [x] préserver les tags existants par défaut et exiger une validation explicite pour leur retrait ;
- [x] utiliser le endpoint PATCH documenté par l'API Joomla ;
- [x] confirmer que le champ `tags` est enregistré sur l'instance Joomla 6 ;
- [x] gérer les erreurs HTTP sans afficher le token ;
- [x] relire l'article après PATCH pour vérifier les tags enregistrés ;
- [x] après une erreur PATCH, relire l'article et distinguer succès effectif, absence de changement ou état inattendu ;
- [x] ne pas écrire directement en base.

---

## Phase 11 — Logs

`apply.py` crée un journal avant le PATCH et le met à jour avec le résultat :

```text
logs/apply-YYYY-MM-DD-HHMMSS-article-ID.json
```

Exemple :

```json
{
  "article_id": 123,
  "before": [18],
  "after": [12, 18]
}
```

- [x] enregistrer l'état avant modification ;
- [x] enregistrer l'état après modification ;
- [x] enregistrer les erreurs ;
- [x] pouvoir identifier facilement les articles modifiés.

---

## Phase 12 — Rollback

Prévoir un mécanisme de restauration à partir des logs.

Exemple cible :

```bash
python rollback.py logs/apply-2026-10-06-1800.json
```

- [ ] restaurer les tags précédents ;
- [ ] fonctionner uniquement avec une option explicite ;
- [ ] proposer un mode dry-run.

---

## Phase 13 — Statistiques

Créer éventuellement :

```bash
python stats.py
```

Exemple de sortie :

```text
Articles total              : 712
Articles sans tags          : 543
Articles analysés           : 712
Articles avec propositions  : 618
Articles ambigus            : 47
Tags proposés               : 1248
```

- [ ] compter les articles sans tags ;
- [ ] compter les propositions par tag ;
- [ ] identifier les tags très peu ou très souvent utilisés ;
- [ ] repérer les articles encore non classés.

---

## Suite immédiate

Les exports, propositions locales et scripts d'application sont en place. Continuer l'analyse des comptes rendus par lots à partir de `data/articles.json`, enregistrer les propositions en attente, puis appliquer uniquement les lots explicitement autorisés. Prévoir ensuite la revue de qualité décrite en phase 9.
