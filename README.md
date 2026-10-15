# Grimperoots Indexer

Ce dépôt exporte les articles et les tags du site Joomla 6 Grimperoots. L’assistant analyse les comptes rendus à partir des fichiers locaux et enregistre les propositions dans `data/proposals.json`. Après autorisation du lot, les tags retenus sont appliqués avec l’API Joomla.

## État du projet

- Les exports Joomla, le référentiel des tags et les propositions sont dans `data/`, ignoré par Git.
- `TAGS.md` décrit les tags disponibles et leurs règles métier.
- L’analyse sémantique est faite dans la conversation à partir du texte complet exporté ; aucune clé ni dépendance de classification externe n’est nécessaire.
- `apply.py <ID> --review` permet de passer interactivement une proposition de `pending` à `ready` ou inversement ; `apply.py --review --all` propose une revue individuelle ou un changement de statut en lot. Ce mode reste local et ignore les propositions `applied`.
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

### Exporter l'index léger des CR

`fetch_cr_index.py` exporte seulement l'ID, le titre et la date des articles publiés dans la catégorie racine Joomla `CRs` (ID 33) et ses sous-catégories. L'URL publique suit la forme `SITE_URL/<ID>` et est reconstruite localement. Le script évite ainsi de télécharger le texte complet et le HTML SIGPlus de chaque article.

Par défaut, la commande affiche une simulation sans contacter l'hébergement :

```bash
./fetch_cr_index.py
```

Pour effectuer l'export :

```bash
./fetch_cr_index.py --apply
```

Le script utilise le relais PHP temporaire déjà employé par `fetch_article_from_db.py` : il le dépose dans la racine Joomla via FTP, exécute un `SELECT` limité à l'ID, au titre et à la date, puis le supprime. Aucune donnée n'est écrite en base. Le résultat est enregistré dans `data/cr_index.json`. `--category-id` permet de sélectionner une autre catégorie racine et `--output` de changer le fichier de sortie. Si la suppression du relais échoue, le script affiche un avertissement indiquant de supprimer via FTP le fichier `fetch-cr-index-*.php` restant.

### Lire un article depuis la base de l'hébergement mutualisé

La base OVH mutualisée n'étant pas accessible depuis l'extérieur, `fetch_article_from_db.py` utilise un relais PHP temporaire. Le mode par défaut est une simulation et ne contacte pas l'hébergement :

```bash
./fetch_article_from_db.py 34
```

Pour effectuer la lecture, il faut utiliser `--apply` :

```bash
./fetch_article_from_db.py 34 --apply
```

Le script dépose par FTP un fichier PHP au nom aléatoire dans `REMOTE_ROOT`, appelle ce fichier sur `SITE_URL` en HTTPS, puis le supprime par FTP. Le PHP charge `configuration.php` et exécute uniquement des `SELECT` paramétrés sur l'article, sa catégorie et ses tags. Si la suppression échoue, le script affiche un avertissement : supprime alors le fichier `fetch-article-*.php` restant dans la racine Joomla via FTP.

La sortie JSON est écrite sur stdout. Pour l'enregistrer localement :

```bash
./fetch_article_from_db.py 34 --apply --output data/article-34.json
```

Les paramètres requis sont `FTP_HOST`, `FTP_USER`, `FTP_PASSWORD`, `SITE_URL` (URL HTTPS de l'installation Joomla) et `REMOTE_ROOT` (racine distante qui contient `configuration.php`), dans `.env.local` ou dans l'environnement. Le script utilise FTPS si `FTP_PLAIN` n'est pas activé. Aucun connecteur Python ni connexion MySQL depuis le poste local n'est requis. Les erreurs n'affichent pas le mot de passe FTP.

Le JSON est un objet plat contenant `id`, `title`, `alias`, `category_id`, `category`, `created`, `introtext`, `fulltext` et `existing_tags`. `introtext` et `fulltext` sont les champs HTML bruts stockés en base ; le script ne lance pas les plugins de contenu Joomla. Ainsi, si un article stocke une directive telle que `{gallery}`, elle reste telle quelle dans le texte SQL. À l'inverse, `data/articles.json` provient de l'API Joomla et place le texte dans `attributes.text` ; l'export local consulté contient du HTML de galerie SIGPlus rendu (653 articles avec `sigplus-gallery`, aucun `{gallery}` littéral). Le HTML, les entités (`&eacute;`) et les directives de plugins ne sont pas normalisés par le script SQL.

Exemple de forme de sortie :

```json
{
  "id": 34,
  "title": "Titre de l'article",
  "alias": "8",
  "category_id": 14,
  "category": "Montagne hiver",
  "created": "2007-02-07 17:17:17",
  "introtext": "<p>Texte d'introduction…</p>",
  "fulltext": "<p>Texte complet…</p>",
  "existing_tags": [25, 28, 33, 35, 36]
}
```

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

Pour examiner une proposition et modifier son statut après validation :

```bash
python3 apply.py 764 --review
python3 apply.py --review --all
```

Le mode interactif affiche le titre, les tags existants et cibles, le diff et les notes. Avec `--all`, tu peux passer toutes les propositions `pending` à `ready`, toutes les `ready` à `pending`, ou décider article par article. Les propositions `applied` sont protégées. `--review` ne contacte pas Joomla et nécessite un terminal interactif.

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
