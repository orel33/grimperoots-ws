# AGENTS.md — Grimperoots Indexer

## Objectif du projet

Ce projet sert à enrichir automatiquement les anciens comptes rendus du site Joomla 6 **Grimperoots** avec les tags Joomla existants.

Le site contient environ :
- 700 articles / comptes rendus ;
- 40 000 photos ;
- 60 comptes utilisateurs.

L'objectif est de construire un pipeline fiable qui :

1. récupère les tags Joomla existants ;
2. récupère les articles via l'API Joomla ;
3. fait lire chaque article complet à un LLM ;
4. propose une liste de tags pertinente pour chaque article ;
5. permet une validation avant toute modification ;
6. applique ensuite les tags validés via l'API Joomla.

---

## Principes impératifs

### 1. Ne jamais travailler par simple détection de mots-clés

La classification doit être **sémantique**.

Le LLM doit lire le contenu complet de l'article et répondre à la question :

> Quels tags décrivent réellement cette sortie ?

et non :

> Quels noms de tags apparaissent dans le texte ?

Une simple mention incidente d'un lieu, d'un massif ou d'une activité ne justifie pas l'ajout d'un tag.

Exemple :

> Un article décrivant une sortie en Corse peut mentionner le Vignemale à titre de comparaison.  
> Cette mention ne doit pas provoquer l'ajout des tags `Vignemale` ou `Pyrénées`.

Le modèle doit identifier :
- le lieu réel de la sortie ;
- l'activité principale ;
- les caractéristiques réellement pertinentes ;
- les tags qui décrivent effectivement le contenu de l'article.

---

### 2. Utiliser uniquement les tags existants

Le système ne doit **jamais créer automatiquement de nouveaux tags Joomla**.

Les tags autorisés sont ceux :
- récupérés depuis Joomla ;
- éventuellement documentés dans un fichier `TAGS.md`.

Le LLM doit choisir uniquement parmi cette liste fermée.

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
Classification LLM
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

Le LLM doit recevoir au minimum :
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

## Classification LLM

Utiliser l'API OpenAI depuis le script, avec le SDK Python officiel et l'API Responses. Le dépôt ne peut pas appeler directement l'assistant de cette conversation : il lui faut une clé API (`OPENAI_API_KEY`), gérée séparément de `JOOMLA_TOKEN` et jamais versionnée. Le modèle sera configurable via `OPENAI_MODEL`, sans être codé en dur. La classification doit demander une sortie structurée conforme à un schéma JSON défini par le projet. L'API OpenAI est facturée séparément d'un abonnement ChatGPT.

Le prompt doit rappeler explicitement les règles suivantes :

- lire l'article dans son ensemble ;
- sélectionner uniquement les tags décrivant réellement la sortie ;
- ne pas utiliser une simple correspondance de mots ;
- ne pas taguer une mention incidente ;
- privilégier le sujet principal de l'article ;
- ne jamais inventer de tag ;
- pouvoir ne proposer aucun nouveau tag ;
- pouvoir signaler les cas ambigus ;
- préserver les tags existants.

La sortie doit être structurée en JSON.

Exemple :

```json
{
  "article_id": 123,
  "suggested_tags": [
    {
      "id": 12,
      "confidence": 0.98
    },
    {
      "id": 18,
      "confidence": 0.91
    }
  ],
  "uncertain_tags": [
    {
      "id": 25,
      "confidence": 0.55,
      "reason": "Le lieu est cité mais ne semble pas être le lieu principal de la sortie."
    }
  ]
}
```

Éviter les longues explications libres.

---

## Validation

Aucune proposition ne doit être appliquée directement après classification.

Le pipeline doit produire un fichier du type :

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

Avant tout `--apply`, prévoir une inspection manuelle d'un échantillon représentatif d'environ 20 à 50 articles.

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
5. classification LLM ;
6. génération de `proposals.json` ;
7. mode `--dry-run` ;
8. validation manuelle ;
9. implémentation du `PATCH` Joomla ;
10. mode `--apply` ;
11. logs et rollback.

Ne pas commencer par la partie écriture.

---

## Commandes cibles

À terme, le projet devrait proposer quelque chose de proche de :

```bash
python export.py
python classify.py
python apply.py --dry-run
python apply.py --dry-run --article=123
python apply.py --dry-run --tag=Corse
python apply.py --apply
python stats.py
```

---

## Style de développement attendu

- privilégier du code simple et lisible ;
- éviter les dépendances inutiles ;
- séparer clairement lecture, classification et écriture ;
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
