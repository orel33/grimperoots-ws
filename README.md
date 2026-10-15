# Grimperoots Web Services

Outils pour exporter des données du site Joomla 6 Grimperoots, compléter les articles avec leurs tags et consulter les champs bruts des comptes rendus. Les commandes se lancent depuis la racine du dépôt.

## Organisation

| Répertoire | Rôle | Outils principaux |
|---|---|---|
| `joomla_api/` | Accès aux Web Services Joomla standards | Export des articles, tags, catégories et auteurs |
| `joomla_custom/` | Endpoints PHP spécifiques et clients Python associés | Index public des CR et lecture protégée du texte brut |
| `tag_indexing/` | Travail local d’indexage | Revue des propositions, application des tags et rendu HTML |

Les données locales restent à la racine : `data/` contient les exports et propositions, `logs/` les journaux d’application et `output/` les rendus HTML. Ces répertoires de données sont ignorés par Git.

## Configuration

Utiliser Python 3.10 ou supérieur. Le fichier `.env.local`, ignoré par Git, contient la configuration des API :

```dotenv
JOOMLA_BASE_URL=https://www.example.org/j6
JOOMLA_TOKEN=jeton-joomla
SITE_URL=https://www.example.org/j6
GRIMPEROOTS_WS_TOKEN=jeton-personnel-du-ws
```

`JOOMLA_TOKEN` sert uniquement aux Web Services Joomla standards. `GRIMPEROOTS_WS_TOKEN` est un secret distinct pour l’endpoint de lecture du texte brut. Le définir aussi dans le fichier non versionné `joomla_custom/www/ws/config.local.php` sur l’hébergement :

```php
<?php
define('GRIMPEROOTS_WS_TOKEN', 'valeur-aleatoire');
```

Générer une valeur avec `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'` et utiliser la même des deux côtés. Le `.htaccess` bloque l’accès web à `config.local.php` et au fichier PHP commun.

---

## 1. `joomla_api/` — API Joomla standard

Ces commandes lisent les données via Joomla Web Services et écrivent les exports dans `data/` :

```bash
python3 -m joomla_api.fetch_tags
python3 -m joomla_api.fetch_categories
python3 -m joomla_api.fetch_authors
python3 -m joomla_api.fetch_articles
```

Fichiers produits : `data/tags.json`, `data/categories.json`, `data/authors.json` et `data/articles.json`. Ces exports sont en lecture seule.

---

## 2. `joomla_custom/` — Endpoints complémentaires

Les endpoints versionnés sont dans `joomla_custom/www/ws/`. Sur l’hébergement actuel, leur destination est `/www/ws/`, à côté de l’installation Joomla `/www/j6/`. Ils chargent sa configuration depuis `/www/j6/configuration.php`.

### Index des comptes rendus

[`cr-index.php`](joomla_custom/www/ws/cr-index.php) sélectionne les articles publiés de la catégorie racine `CRs` (ID 33) et de ses sous-catégories. Il renvoie uniquement l’ID, le titre et la date. Le JSON est utilisé par le client Python ; l’ouverture dans un navigateur affiche une table HTML :

[https://www.grimperoots.fr/ws/cr-index.php](https://www.grimperoots.fr/ws/cr-index.php)

Exporter localement la liste :

```bash
python3 -m joomla_custom.fetch_cr_index
```

Le fichier `data/cr_index.json` inclut une URL reconstruite à partir de l’ID. `--category-id` permet de choisir une autre catégorie et `--output` de modifier le fichier de sortie. `--dry-run` affiche la requête sans la lancer.

### Texte brut d’un article

[`article.php`](joomla_custom/www/ws/article.php) récupère les champs `introtext` et `fulltext` stockés en base, ainsi que les tags. Il ne lance pas les plugins Joomla : une directive comme `{gallery}` est donc conservée. L’endpoint exige le header `X-Grimperoots-Token` ; l’ID seul ne permet pas de consulter le contenu brut.

```bash
python3 -m joomla_custom.fetch_article 802
python3 -m joomla_custom.fetch_article 802 --output data/article-802.json
```

La sortie contient `id`, `title`, `alias`, `category_id`, `category`, `created`, `introtext`, `fulltext` et `existing_tags`. `--dry-run` simule la requête. L’ancien `--apply` reste accepté comme alias de compatibilité et ne provoque aucune écriture.

Ces endpoints utilisent uniquement des requêtes SQL `SELECT`. Les outils Python les appellent en HTTPS et ne déposent plus de fichiers temporaires par FTP.

---

## 3. `tag_indexing/` — Indexage des tags

L’analyse se fait dans la conversation à partir des exports locaux. Lire le compte rendu complet, sa catégorie et ses tags actuels ; comparer les faits aux tags Joomla et à leurs descriptions dans [tag_indexing/TAGS.md](tag_indexing/TAGS.md). Ne pas appeler d’API de classification externe. Les ajouts sont proposés par défaut ; préserver les tags existants et ne proposer des retraits qu’après validation explicite.

Les suites prévues sont résumées dans la [feuille de route](tag_indexing/ROADMAP.md).

### Propositions

Avant un nouveau cycle, actualiser les articles et les tags, puis archiver les propositions précédentes :

```bash
python3 -m joomla_api.fetch_articles
python3 -m joomla_api.fetch_tags
python3 -m tag_indexing.init_proposals
```

L’assistant ajoute ses propositions dans `data/proposals.json` avec `status: "pending"`. Après validation, chaque entrée passe à `ready` et contient l’état complet `existing_tags` ainsi que la cible complète `final_tags`. Les propositions `applied` indiquent que Joomla a confirmé l’écriture par relecture.

### Revue et application

Revoir localement les propositions et changer leur statut :

```bash
python3 -m tag_indexing.apply 802 --review
python3 -m tag_indexing.apply --review --all
```

Inspecter les propositions `ready` sans écrire :

```bash
python3 -m tag_indexing.apply --all --dry-run
```

Appliquer les propositions validées à Joomla :

```bash
python3 -m tag_indexing.apply --all --apply
```

Toute écriture exige `--apply`. Le PATCH contient uniquement l’ID de l’article et la liste finale des IDs de tags, par exemple `{"id": 802, "tags": [33, 36]}`. Il ne renvoie pas le titre, le texte, les images ni le reste du contenu de l’article. Les journaux d’application vont dans `logs/`.

Sur l’instance actuelle, JComments peut faire répondre HTTP 500 à Joomla après le PATCH et laisser l’article verrouillé, même quand la relecture confirme les tags. L’application désactive donc temporairement son plugin avant l’écriture et le réactive ensuite. Détails dans [tag_indexing/BUGS.md](tag_indexing/BUGS.md).

### Rendu HTML

Générer un rendu à partir des JSON locaux :

```bash
python3 -m tag_indexing.render_article 802
```

Le fichier et sa feuille de style sont écrits dans `output/`.
