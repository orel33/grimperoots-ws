# AGENTS.md — Grimperoots Indexer

## Objectif du projet

Ce projet sert à enrichir automatiquement les anciens comptes rendus du site Joomla 6 **Grimperoots** avec les tags Joomla existants.

Le site contient environ :
- 700 articles / comptes rendus ;
- 40 000 photos ;
- 60 comptes utilisateurs.

L'objectif est de construire un processus fiable qui :

1. récupère les tags Joomla existants ;
2. récupère les articles via l'API Joomla ;
3. fait analyser chaque article complet par l'assistant depuis les fichiers locaux ;
4. prépare les propositions dans `data/proposals.json` ;
5. applique seulement un lot explicitement autorisé via l'API Joomla ;
6. permet une revue de qualité après application et corrige les propositions si nécessaire.

## État actuel

Les scripts en place couvrent l'export des tags, catégories, comptes auteurs et articles (`fetch_tags.py`, `fetch_categories.py`, `fetch_authors.py`, `fetch_articles.py`). L'assistant analyse les articles directement dans les exports locaux et prépare les propositions dans `data/proposals.json` ; aucune API OpenAI n'est utilisée par le dépôt. `render_article.py <id>` génère le HTML d'un article depuis `data/articles.json`. `apply.py <id>` traite une proposition `ready` ; `apply.py --all` traite toutes les propositions `ready` une par une. Après confirmation Joomla, leur statut devient `applied`. Sans `--apply`, ces commandes restent en simulation. Les exports et propositions sont dans `data/`, ignoré par Git, et les journaux d'écriture dans `logs/`, également ignoré par Git.

---

## Principes impératifs

### 1. Ne jamais travailler par simple détection de mots-clés

L'analyse doit être **sémantique**.

L'assistant doit lire le contenu complet de l'article et répondre à la question :

> Quels tags décrivent réellement cette sortie ?

et non :

> Quels noms de tags apparaissent dans le texte ?

Une simple mention incidente d'un lieu, d'un massif ou d'une activité ne justifie pas l'ajout d'un tag.

Exemple :

> Un article décrivant une sortie en Corse peut mentionner le Vignemale à titre de comparaison.  
> Cette mention ne doit pas provoquer l'ajout des tags `Vignemale` ou `Pyrénées`.

L'analyse doit identifier :
- le lieu réel de la sortie ;
- l'activité principale ;
- les caractéristiques réellement pertinentes ;
- les tags qui décrivent effectivement le contenu de l'article.

La catégorie Joomla est un indice fiable et fort du contexte de l'article. `Montagne été` et `Montagne hiver` indiquent fortement la saison et le cadre de la sortie ; `Canyoning` indique fortement que le canyon est au cœur du compte rendu. Utiliser ces catégories pour orienter l'interprétation des tags correspondants, en les confrontant au récit complet pour identifier l'activité précise.

La marche d'approche, même longue ou difficile, ne justifie pas le tag `Randonnée` lorsqu'elle sert une activité principale comme la cascade de glace, l'escalade, le ski de randonnée, l'alpinisme ou le canyon. Une randonnée secondaire à ces activités dominantes ne justifie pas non plus le tag. `Randonnée` désigne un trek ou une randonnée pédestre pratiquée comme activité ; elle coexiste rarement avec ces tags et ne s'y ajoute que si un trek distinct est décrit de manière substantielle dans le compte rendu. Une mention incidente d'autres participants faisant une randonnée ne suffit pas. Une randonnée en montagne l'hiver dans la neige relève de `Ski de Rando`, que le déplacement se fasse à skis ou en raquettes, même si le récit ne précise pas le matériel.

Le tag `Famille` s'applique uniquement lorsque le compte rendu indique explicitement que des enfants participent à la sortie avec leurs parents. Ne pas le déduire d'une simple mention de famille, d'un couple ou d'un groupe d'amis.

---

### 2. Utiliser uniquement les tags existants

Le système ne doit **jamais créer automatiquement de nouveaux tags Joomla**.

Les tags autorisés sont ceux :
- récupérés depuis Joomla ;
- éventuellement documentés dans un fichier `TAGS.md`.

L'assistant doit choisir uniquement parmi cette liste fermée.

---

### 3. Préserver les tags existants

Ne jamais supprimer automatiquement un tag déjà associé à un article.

Par défaut :

```text
tags_finaux = tags_existants ∪ tags_validés
```

Le premier objectif est l'enrichissement des anciens articles, pas le nettoyage automatique de la taxonomie.

---

## Sécurité

### Accès Joomla

Utiliser exclusivement l'API Web Services Joomla 6.

Ne jamais modifier directement la base de données Joomla.

En particulier, ne pas écrire directement dans :

```text
#__contentitem_tag_map
```

Le token Joomla doit être lu depuis une variable d'environnement, par exemple :

```bash
export JOOMLA_TOKEN='...'
```

Ne jamais :
- stocker le token dans le dépôt Git ;
- écrire un token dans un fichier versionné ;
- afficher le token dans les logs.

Un éventuel fichier `.env` doit être ajouté à `.gitignore`.

---

## Politique d'écriture

Le comportement par défaut doit être **sans modification du site**.

Toute opération d'écriture doit nécessiter une option explicite :

```bash
--apply
```

Un mode de simulation doit toujours être disponible :

```bash
--dry-run
```

Exemples :

```bash
python apply.py --dry-run
python apply.py --apply
```

Ne jamais introduire une écriture automatique par défaut.

---

## Architecture souhaitée

```text
Joomla 6 API
     |
     | GET tags / articles
     v
Données locales JSON
     |
     v
Analyse de l'assistant depuis les fichiers locaux
     |
     v
proposals.json
     |
     | validation / inspection
     v
PATCH API Joomla
```

Les différentes étapes doivent rester découplées.

---

## Données d'un article

Pour chaque article, récupérer au minimum :

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

L'assistant doit lire au minimum :
- le titre ;
- la catégorie Joomla ;
- la date ;
- `introtext` ;
- `fulltext` ;
- les tags existants ;
- la liste complète des tags autorisés ;
- éventuellement la description métier des tags.

Ne pas télécharger les images pour la première version du système.

---

## Analyse sémantique par l'assistant

L'assistant travaille à partir des exports présents dans `data/`. Ne pas appeler l'API OpenAI, ne pas transmettre le contenu à un service de classification externe et ne demander ni clé OpenAI ni SDK.

Pour chaque article demandé par l'utilisateur, lire le texte complet ainsi que le titre, la catégorie, la date et les tags actuels. Comparer les faits de l'article à la liste fermée des tags de `data/tags.json` et à leurs descriptions dans `TAGS.md`. Produire une proposition courte dans `data/proposals.json` avec `status=pending`, puis présenter les associations et retraits envisagés dans un tableau `+Tag` / `-Tag`. Les ajouts sont proposés par défaut ; les retraits restent exclus, sauf demande ou validation explicite de l'utilisateur.

L'analyse doit suivre ces règles :

- lire l'article dans son ensemble ;
- sélectionner uniquement les tags décrivant réellement la sortie ;
- ne pas utiliser une simple correspondance de mots ;
- ne pas taguer une mention incidente ;
- privilégier le sujet principal de l'article ;
- ne jamais inventer de tag ;
- pouvoir ne proposer aucun nouveau tag ;
- pouvoir signaler les cas ambigus ;
- préserver les tags existants.

Les propositions locales suivent le format JSON de `data/proposals.json`. Ajouter ou mettre à jour une entrée par ID d'article sans remplacer les entrées des autres articles. Une entrée contient `existing_tags` (état complet de départ), `final_tags` (cible complète), `status` et, si utile, `notes`. `pending` signifie qu'une suggestion attend validation ; `ready` signifie que l'utilisateur a validé ou explicitement donné la cible ; `applied` signifie que Joomla a confirmé la cible par relecture. Les notes sont facultatives et peuvent expliquer une décision métier à intégrer ensuite dans `TAGS.md`. Ne pas ajouter de métadonnées propres à un modèle ou à une API de classification.

Pour ouvrir une campagne distincte, actualiser d'abord les exports Joomla nécessaires, puis utiliser `init_proposals.py`. Ce script archive le cycle précédent sous `data/archive/` et initialise `data/proposals.json` à `{}`. Ne pas préremplir les propositions pour tous les articles : `data/articles.json` conserve déjà leur état courant complet, tandis que `proposals.json` suit uniquement les articles analysés pendant le cycle.

Garder les propositions courtes ; les raisons et arbitrages sont présentés dans la conversation ou, si utile, dans `notes` au niveau de l'entrée.

---

## Validation

Aucune proposition ne doit être appliquée automatiquement après analyse. Les suggestions restent en `pending` et `apply.py` les ignore. L'assistant affiche le diff du lot ; lorsque l'utilisateur accepte la suggestion ou donne explicitement la cible, renseigner la liste complète `final_tags` et passer `status` à `ready`. Lancer d'abord un dry-run ; toute écriture exige ensuite `--apply`. Après relecture Joomla confirmant la cible, `apply.py` passe `status` à `applied`. `apply.py --all` ne traite que les entrées `ready`. Une revue de qualité approfondie peut être faite après l'application du lot.

Le pipeline doit produire un fichier du type :

```text
data/proposals.json
```

Exemple :

```json
{
  "123": {
    "existing_tags": [18],
    "final_tags": [12, 18],
    "status": "pending",
    "notes": "Ajouter le tag correspondant au massif réellement parcouru."
  }
}
```

Après application d'un lot, prévoir une revue de qualité d'un échantillon représentatif d'environ 20 à 50 articles au fil de l'avancement. Les propositions et journaux permettent de corriger les tags lors d'un lot ultérieur.

Tester notamment :
- sorties clairement géolocalisées ;
- articles avec plusieurs lieux cités ;
- mentions incidentes d'autres massifs ;
- articles très courts ;
- vieux articles ;
- articles avec plusieurs activités.

---

## Logs et traçabilité

Toute écriture Joomla doit produire un log.

Exemple :

```text
logs/apply-YYYY-MM-DD-HHMM.json
```

Avec au minimum :

```json
{
  "article_id": 123,
  "before": [18],
  "after": [12, 18]
}
```

Le but est de pouvoir :
- auditer les modifications ;
- retrouver les articles modifiés ;
- préparer un éventuel rollback.

---

## Ordre de développement

Respecter cet ordre :

1. accès API Joomla ;
2. export local des tags ;
3. export local des articles ;
4. génération des fichiers JSON ;
5. analyse des articles par l'assistant depuis les exports locaux ;
6. enregistrement des propositions en attente dans `data/proposals.json` ;
7. mode `--dry-run` ;
8. autorisation explicite du lot, puis validation des propositions retenues ;
9. `PATCH` Joomla et vérification par relecture ;
10. revue de qualité après application ;
11. journaux et rollback.

Ne pas commencer par la partie écriture.

---

## Commandes cibles

À terme, le projet devrait proposer quelque chose de proche de :

```bash
python export.py
python apply.py --all --dry-run
python apply.py --all --apply
python stats.py
```

---

## Style de développement attendu

- privilégier du code simple et lisible ;
- éviter les dépendances inutiles ;
- séparer clairement lecture, analyse et écriture ;
- produire des erreurs explicites ;
- rendre les opérations idempotentes autant que possible ;
- conserver les données locales nécessaires au débogage ;
- ne jamais masquer une erreur API ;
- documenter les formats JSON utilisés.

---

## Règle générale

En cas de doute :
- ne pas écrire dans Joomla ;
- conserver les tags existants ;
- signaler l'ambiguïté ;
- préférer un résultat incomplet mais sûr à une modification incorrecte.
