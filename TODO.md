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

## Phase 5 — Classification LLM

Fournisseur retenu : API OpenAI, appelée avec le SDK Python officiel et l'API Responses. Utiliser une sortie structurée JSON Schema. Lire `OPENAI_API_KEY` depuis l'environnement et configurer le nom du modèle via `OPENAI_MODEL`; ne jamais versionner la clé. L'usage API est facturé séparément de ChatGPT. Choisir le modèle définitif après évaluation sur un échantillon représentatif.

Le premier script traite un article à la fois. La procédure d'installation, de configuration et d'exécution est documentée dans `README.md`.

```bash
python classify.py 802
```

`classify.py <ID>` lit `data/articles.json`, `data/tags.json`, et si disponibles `data/categories.json` et `data/authors.json`. Il transmet au modèle le contenu complet de l'article, les relations connues, la liste fermée des tags Joomla et leurs descriptions depuis `TAGS.md`. Le prompt de référence est `prompts/classify_article.md` ; le schéma de sortie est `schemas/classification.schema.json`.

Le programme écrit ou met à jour l'entrée de cet article dans `data/proposals.json`. Il ne contacte Joomla que pour les exports effectués par les scripts `fetch_*`; la classification elle-même ne fait aucun appel d'écriture au site. `--dry-run` résume les données préparées sans appeler OpenAI ni créer de proposition.

La clé `OPENAI_API_KEY` et le modèle `OPENAI_MODEL` doivent être configurés dans l'environnement, `.env` ou `.env.local`. Le SDK Python `openai` doit être installé. Les appels à l'API sont facturés indépendamment d'un abonnement ChatGPT.

Pour chaque article, envoyer au modèle :
- [x] titre ;
- [x] catégorie ;
- [x] date ;
- [x] texte éditorial complet (`introtext`/`fulltext` si séparés, sinon champ combiné `text`) ;
- [x] tags existants ;
- [x] tags autorisés ;
- [x] descriptions métier de `TAGS.md`.

Règles du prompt :
- [x] classification sémantique ;
- [x] lecture de l'article complet ;
- [x] pas de simple matching de mots-clés ;
- [x] pas de tag pour une mention incidente ;
- [x] aucun nouveau tag inventé ;
- [x] possibilité de ne proposer aucun nouveau tag ;
- [x] possibilité de signaler une ambiguïté ;
- [x] conservation des tags existants.

---

## Phase 6 — Format de sortie

Utiliser une sortie JSON structurée. Le schéma de sortie est préparé dans `schemas/classification.schema.json`.

Exemple :

```json
{
  "article_id": 123,
  "suggested_tags": [
    {
      "id": 12,
      "confidence": 0.98
    }
  ],
  "uncertain_tags": [
    {
      "id": 25,
      "confidence": 0.55,
      "reason": "Le lieu est mentionné mais ne semble pas être le lieu principal."
    }
  ]
}
```

- [x] Demander une sortie OpenAI Structured Outputs conforme au schéma et vérifier localement les IDs de tags et les champs reçus.
- [x] Signaler les erreurs d'entrée, de réponse et d'appel API.
- [x] Relancer un article précis avec `python classify.py <ID>`.

---

## Phase 7 — Génération de `proposals.json`

`classify.py <ID>` crée ou met à jour l'entrée de l'article dans :

```text
data/proposals.json
```

Exemple :

```json
{
  "123": {
    "title": "Traversée de Bavella",
    "existing_tags": [18],
    "suggested_tags": [12, 18],
    "new_tags": [12],
    "uncertain_tags": []
  }
}
```

Règle :

```text
tags_finaux = tags_existants UNION tags_validés
```

- [x] Ne jamais supprimer automatiquement les tags existants.
- [x] Distinguer clairement :
  - tags existants ;
  - tags proposés ;
  - nouveaux tags ;
  - tags incertains.

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

Avant toute écriture :

- [ ] contrôler entre 20 et 50 articles (8 articles discutés/validés à ce jour) ;
- [ ] vérifier plusieurs types de sorties ;
- [ ] vérifier les articles courts ;
- [ ] vérifier les articles contenant plusieurs lieux ;
- [ ] vérifier les mentions incidentes ;
- [ ] vérifier les articles avec plusieurs activités ;
- [ ] corriger le prompt si nécessaire ;
- [ ] relancer la classification avant de passer à l'écriture.

---

## Phase 10 — Écriture Joomla

Le mode global `--all --apply` a été lancé sur les 8 propositions validées le 8 octobre 2026. Sept articles ont été modifiés ; le CR 764 était déjà conforme. Pour les sept PATCH, Joomla a répondu HTTP 500, mais chaque relecture API a confirmé les tags finaux. La trace récupérée par FTP après un PATCH identique sur le CR 795 montre que le plugin de contenu `JComments` plante pendant `onContentAfterSave` : il appelle `Route::_()` dans le contexte API, ce qui aboutit à `Call to undefined method Joomla\CMS\Router\ApiRouter::build()`. Le manifeste installé indique JComments 5.0.6 et le journal Joomla indique Joomla 6.1.4. La sauvegarde de l'article et des tags a lieu avant cette erreur post-save ; une relecture confirme `[33, 36]`. Le corps HTTP reste générique (`{"errors":{"code":500,"title":"Internal server error"}}`).

Prochaine action d'écriture à différer jusqu'à correction ou contournement contrôlé du plugin : vérifier une mise à jour compatible de Joomla/JComments ou appliquer une correction au plugin en environnement de test, puis confirmer qu'un PATCH ne renvoie plus 500.

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

## Priorité immédiate

Commencer uniquement par :

```text
Joomla API
    ↓
Export JSON local
```

Aucune écriture Joomla tant que :
- l'export n'est pas fiable ;
- les tags existants ne sont pas correctement lus ;
- la classification n'a pas été validée manuellement.
