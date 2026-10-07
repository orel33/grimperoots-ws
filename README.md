# Grimperoots Indexer

Ce dépôt exporte les tags et les articles de Joomla, puis prépare des propositions d'indexage assistées par un modèle OpenAI. Les propositions doivent être relues et validées avant toute modification du site.

## État du projet

- Les exports Joomla sont enregistrés dans `data/`.
- `TAGS.md` documente les tags existants. Les définitions métier sont encore provisoires et doivent être validées.
- `classify.py <ID>` traite un seul article et ajoute sa proposition dans `data/proposals.json`.
- `apply.py <ID>` inspecte une proposition validée ; `apply.py --all` parcourt toutes les propositions validées. Sans `--apply`, ces commandes fonctionnent en simulation.

## Prérequis

- Python 3.10 ou supérieur.
- Une clé API Joomla pour rafraîchir les exports.
- Le SDK Python OpenAI pour classifier un article :

```bash
python3 -m pip install openai
```

Le SDK Python officiel utilise l'API Responses pour les nouvelles intégrations. Le classificateur demande une sortie structurée conforme à `schemas/classification.schema.json` ([documentation OpenAI](https://developers.openai.com/api/docs/guides/structured-outputs)).

## Configuration locale

Les scripts lisent `.env.local` à la racine du dépôt. Ce fichier est ignoré par Git. Ne publie jamais les clés qu'il contient.

```dotenv
JOOMLA_BASE_URL=https://www.example.org/j6
JOOMLA_TOKEN=jeton-joomla

OPENAI_API_KEY=cle-api-openai
OPENAI_MODEL=identifiant-du-modele
```

La classification locale n'a pas besoin de `JOOMLA_BASE_URL` ni de `JOOMLA_TOKEN` si les fichiers JSON sont déjà présents. `OPENAI_MODEL` doit être le nom d'un modèle accessible au projet API et compatible avec Structured Outputs.

### Créer une clé API OpenAI

1. Connecte-toi à la [plateforme API OpenAI](https://platform.openai.com/).
2. Dans les paramètres d'un projet, ouvre **API Keys**, puis sélectionne **Create new secret key**. La clé complète n'est affichée qu'à sa création ; conserve-la dans `.env.local` ou un gestionnaire de secrets ([aide sur les clés API](https://help.openai.com/en/articles/4936850-where-do-i-find-my-openai-api-key)).
3. Configure la facturation de la plateforme API si nécessaire.

ChatGPT Plus et l'utilisation de l'API sont deux facturations distinctes ; Plus ne fournit pas de crédit API ([détails de l'abonnement Plus](https://help.openai.com/en/articles/6950777-what-is-chatgpt-plus)). Pour les comptes API en prépaiement, vérifie le montant de crédit et désactive le rechargement automatique si tu ne le souhaites pas ([facturation prépayée](https://help.openai.com/en/articles/8264644-setting-up-and-managing-prepaid-api-billing)).

## Actualiser les exports Joomla

Si les exports locaux sont absents ou anciens, configure les variables Joomla dans `.env.local`, puis lance :

```bash
python3 fetch_tags.py
python3 fetch_categories.py
python3 fetch_authors.py
python3 fetch_articles.py
```

Les scripts exportent respectivement vers `data/tags.json`, `data/categories.json`, `data/authors.json` et `data/articles.json`. Ils utilisent l'API Joomla en lecture seule.

## Classifier un article

### Entrées de `classify.py <ID>`

| Entrée | Rôle |
| --- | --- |
| `data/articles.json` | Article complet : titre, texte, date et relations disponibles. |
| `data/tags.json` | Liste fermée des tags Joomla autorisés. |
| `data/categories.json` | Noms de catégories associés à leurs IDs, si le fichier existe. |
| `data/authors.json` | Noms d'auteurs associés à leurs IDs, si le fichier existe. |
| `TAGS.md` | Descriptions métier. Les IDs et intitulés doivent correspondre à `tags.json`. |
| `prompts/classify_article.md` | Consignes d'analyse sémantique et de réponse. |
| `schemas/classification.schema.json` | Format JSON imposé à la réponse du modèle. |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | Accès à l'API et modèle utilisé. |

Le script transmet le texte complet de l'article à l'API OpenAI. Dans l'export Joomla actuel, le corps est généralement le champ combiné `text` en HTML plutôt que deux champs `introtext` et `fulltext`. Les images ne sont pas téléchargées. Le contenu est envoyé pour cette requête de classification ; le coût dépend du modèle et du volume de texte traité.

### Prévisualiser sans appel API

```bash
python3 classify.py 802 --dry-run
```

Cette commande affiche l'article sélectionné, la longueur du texte et le nombre de tags existants/autorisés. Elle ne demande pas de clé API et n'écrit pas de proposition ; `OPENAI_MODEL` doit tout de même être configuré.

### Appeler le modèle

```bash
python3 classify.py 802
```

Cette commande effectue un appel facturable à l'API OpenAI. Elle ne nécessite pas de token Joomla et n'écrit rien sur le site.

### Sortie

Le script crée ou met à jour `data/proposals.json`, indexé par ID d'article. Exemple simplifié :

```json
{
  "802": {
    "title": "Compte rendu de sortie",
    "existing_tags": [20, 21],
    "suggested_tags": [20, 33],
    "new_tags": [33],
    "uncertain_tags": [
      {
        "id": 34,
        "confidence": 0.55,
        "reason": "La randonnée semble secondaire dans ce récit."
      }
    ],
    "confidence_by_tag": {
      "20": 0.98,
      "33": 0.91
    },
    "model": "identifiant-du-modele",
    "classified_at": "date-heure-UTC"
  }
}
```

`suggested_tags` peut comprendre des tags déjà présents si le modèle estime qu'ils décrivent bien l'article. `new_tags` est la différence avec `existing_tags`. Une nouvelle classification de l'article remplace son entrée, tout en conservant les entrées des autres articles. Le fichier `data/` est local et ignoré par Git.

Relis les propositions avant toute application. Le script d'application bloque les propositions non validées et toute suppression de tag qui n'a pas été approuvée explicitement. Sans `--apply`, aucune écriture n'est envoyée à Joomla.

## Appliquer une proposition à Joomla

Le script peut traiter un article ou toutes les propositions validées. Pour chaque article, il relit les tags via l'API Joomla, vérifie qu'ils correspondent à `existing_tags` dans la proposition, vérifie la liste finale contre `data/tags.json`, puis affiche les différences sous la forme `+Tag (ID)` et `-Tag (ID)`. Les propositions non validées sont ignorées et listées. Si PATCH renvoie une erreur, le script relit l'article pour déterminer si la cible a malgré tout été enregistrée, si rien n'a changé ou si l'état reste incertain.

```bash
python3 apply.py 764 --dry-run
python3 apply.py 764 --apply
python3 apply.py --all --dry-run
python3 apply.py --all --apply
```

Exemple de simulation :

```text
[1/8] Article 764 — Les Segpa au ski de rando
  +Pyrénées (33)  -Randonnée (34)
  Simulation : aucun PATCH envoyé.
```

La simulation est aussi le comportement par défaut (`python3 apply.py 764` ou `python3 apply.py --all`). Toute écriture utilise `PATCH /api/index.php/v1/content/articles/{id}` avec le champ `tags`. Les tags existants sont conservés sauf si leur retrait figure explicitement dans la revue humaine validée de la proposition. Après chaque PATCH, le script relit l'article pour vérifier le résultat. En mode `--all`, chaque article est traité séparément ; une erreur sur un article est signalée et le traitement continue avec les suivants. Le code de sortie final indique si au moins un article a échoué. En cas d'erreur HTTP, un extrait tronqué de la réponse Joomla est inclus dans le message et le journal ; le token est masqué.

Avant une application globale, inspecte un échantillon représentatif de 20 à 50 articles et vérifie le résumé en simulation. Les propositions non validées ne sont jamais appliquées.

Chaque tentative d'écriture produit un journal local dans `logs/`, ignoré par Git, avec les tags avant/après, les ajouts, les suppressions et le résultat de la vérification. Le script ne fait aucune écriture pendant une simulation.

## Rendu HTML

Pour générer le HTML d'un article exporté :

```bash
python3 render_article.py 802
```

Le fichier est écrit dans `output/`.
