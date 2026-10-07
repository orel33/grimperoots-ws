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
- [ ] Tester la récupération de la liste des articles.
- [x] Tester la récupération d'un article précis (article 22).
- [x] Implémenter la pagination pour les exports de tags, catégories et auteurs.
- [ ] Vérifier la pagination avec une collection qui dépasse la limite d'une page.
- [x] Tester la récupération des catégories et des auteurs.

Endpoints à tester :

```text
GET /api/index.php/v1/tags
GET /api/index.php/v1/content/articles
GET /api/index.php/v1/content/articles/{id}
```

---

## Phase 3 — Export local

Créer un script d'export global (à faire) :

```bash
python export.py
```

Il doit :

- [x] récupérer tous les tags (`fetch_tags.py`) ;
- [ ] récupérer tous les articles ;
- [x] sauvegarder les tags dans `data/tags.json` ;
- [ ] sauvegarder les articles dans `data/articles/`.

Exports complémentaires déjà disponibles : `fetch_categories.py` produit `data/categories.json`, `fetch_authors.py` produit `data/authors.json` (ID et nom uniquement), et `fetch_article.py` récupère un article individuel avec ses relations Joomla. L'ID de catégorie et l'ID de l'auteur restent associés dans le JSON de l'article ; la résolution des noms dans cet export reste à intégrer.

Structure cible :

```text
data/
├── tags.json
└── articles/
    ├── 123.json
    ├── 124.json
    └── ...
```

Pour chaque article, conserver au minimum :

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
- [ ] Ne pas télécharger les images.

---

## Phase 4 — Documentation de la taxonomie

Créer `TAGS.md`.

Pour chaque tag :
- [ ] nom ;
- [ ] identifiant Joomla ;
- [ ] définition ;
- [ ] cas d'utilisation ;
- [ ] cas où le tag ne doit pas être utilisé.

Exemple :

```markdown
## Corse

Utiliser lorsque la sortie décrite dans l'article se déroule réellement en Corse.

Ne pas utiliser pour une simple mention de la Corse.
```

---

## Phase 5 — Classification LLM

Fournisseur retenu : API OpenAI, appelée avec le SDK Python officiel et l'API Responses. Utiliser une sortie structurée JSON Schema. Lire `OPENAI_API_KEY` depuis l'environnement et configurer le nom du modèle via `OPENAI_MODEL`; ne jamais versionner la clé. L'usage API est facturé séparément de ChatGPT. Choisir le modèle définitif après évaluation sur un échantillon représentatif.

Créer un script :

```bash
python classify.py
```

Pour chaque article, envoyer au modèle :
- [ ] titre ;
- [ ] catégorie ;
- [ ] date ;
- [ ] `introtext` ;
- [ ] `fulltext` ;
- [ ] tags existants ;
- [ ] tags autorisés ;
- [ ] descriptions éventuelles de `TAGS.md`.

Règles du prompt :
- [ ] classification sémantique ;
- [ ] lecture de l'article complet ;
- [ ] pas de simple matching de mots-clés ;
- [ ] pas de tag pour une mention incidente ;
- [ ] aucun nouveau tag inventé ;
- [ ] possibilité de ne proposer aucun nouveau tag ;
- [ ] possibilité de signaler une ambiguïté ;
- [ ] conservation des tags existants.

---

## Phase 6 — Format de sortie

Utiliser une sortie JSON structurée.

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

- [ ] Valider le JSON renvoyé.
- [ ] Gérer proprement les erreurs de classification.
- [ ] Permettre de relancer uniquement les articles en erreur.

---

## Phase 7 — Génération de `proposals.json`

Créer :

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

- [ ] Ne jamais supprimer automatiquement les tags existants.
- [ ] Distinguer clairement :
  - tags existants ;
  - tags proposés ;
  - nouveaux tags ;
  - tags incertains.

---

## Phase 8 — Inspection et dry-run

Créer :

```bash
python apply.py --dry-run
```

Affichage souhaité :

```text
Article 123 — Traversée de Bavella

Tags existants :
  Escalade

Tags proposés :
  Corse

Tags finaux :
  Escalade
  Corse
```

Ajouter si utile :

```bash
python apply.py --dry-run --article=123
python apply.py --dry-run --tag=Corse
```

- [ ] Prévoir éventuellement une sortie CSV.
- [ ] Pouvoir inspecter facilement les cas ambigus.
- [ ] Ne faire aucune écriture dans ce mode.

---

## Phase 9 — Validation manuelle

Avant toute écriture :

- [ ] contrôler entre 20 et 50 articles ;
- [ ] vérifier plusieurs types de sorties ;
- [ ] vérifier les articles courts ;
- [ ] vérifier les articles contenant plusieurs lieux ;
- [ ] vérifier les mentions incidentes ;
- [ ] vérifier les articles avec plusieurs activités ;
- [ ] corriger le prompt si nécessaire ;
- [ ] relancer la classification avant de passer à l'écriture.

---

## Phase 10 — Écriture Joomla

Implémenter seulement après validation :

```bash
python apply.py --apply
```

- [ ] utiliser l'API Joomla ;
- [ ] tester d'abord sur 2 ou 3 articles ;
- [ ] envoyer l'ensemble final des tags voulu ;
- [ ] préserver les tags existants ;
- [ ] vérifier le format exact attendu par l'API Joomla 6 ;
- [ ] gérer les erreurs HTTP proprement ;
- [ ] ne pas écrire directement en base.

---

## Phase 11 — Logs

Créer des logs du type :

```text
logs/apply-YYYY-MM-DD-HHMM.json
```

Exemple :

```json
{
  "article_id": 123,
  "before": [18],
  "after": [12, 18]
}
```

- [ ] enregistrer l'état avant modification ;
- [ ] enregistrer l'état après modification ;
- [ ] enregistrer les erreurs ;
- [ ] pouvoir identifier facilement les articles modifiés.

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
