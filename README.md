# Grimperoots Web Services

Outils pour exporter des données du site Joomla 6 Grimperoots, compléter les articles avec leurs tags et consulter les champs bruts des comptes rendus. Les commandes se lancent depuis la racine du dépôt.

## Organisation

| Répertoire | Rôle | Outils principaux |
|---|---|---|
| `joomla_api/` | Accès aux Web Services Joomla standards | Export des articles, tags, catégories et auteurs |
| `joomla_custom/` | Endpoints PHP spécifiques, clients et déploiement | Index des CR, lecture protégée et inventaire des photos |
| `tag_indexing/` | Travail local d’indexage | Revue des propositions, application des tags et rendu HTML |

Les données locales restent à la racine : `data/` contient les exports et propositions, `logs/` les journaux d’application et `output/` les rendus HTML. Ces répertoires de données sont ignorés par Git.

## Configuration

Utiliser Python 3.10 ou supérieur. `.env.example` liste les variables nécessaires. Reporter et compléter ces valeurs dans `.env.local`, qui est ignoré par Git. Le fichier `.env` séparé n’est pas nécessaire lorsque `.env.local` contient ces valeurs :

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

Générer une valeur avec `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'` et utiliser exactement la même des deux côtés. Le `.htaccess` bloque l’accès web direct à `config.local.php` et au fichier PHP commun.

#### Modifier ou renouveler le jeton

Le jeton existe en deux endroits : dans `.env.local` pour les clients Python, et dans `/www/ws/config.local.php` sur OVH pour le serveur. `deploy_ws.py` ne transfère pas ce fichier lors du déploiement ordinaire d’un endpoint. Pour générer un nouveau jeton et synchroniser les deux emplacements :

```bash
python3 -m joomla_custom.deploy_ws --token --dry-run
python3 -m joomla_custom.deploy_ws --token --apply
```

La simulation n’engendre aucun jeton. Avec `--apply`, le script génère un secret aléatoire sans l’afficher, met à jour uniquement la définition `GRIMPEROOTS_WS_TOKEN` dans le `config.local.php` distant, relit le fichier pour vérifier le transfert, puis vérifie le jeton par HTTPS avant d’enregistrer la même valeur dans `.env.local`. Il refuse de procéder si `.htaccess` ne bloque pas l’accès web à `config.local.php`. En cas d’échec avant la mise à jour locale, il tente de restaurer la configuration OVH précédente. L’écriture locale remplace le fichier de manière atomique et lui applique les permissions `600`.

La vérification HTTPS appelle `article.php?id=0` : le WS vérifie d’abord le jeton et répond ensuite `Invalid id`. Cette réponse HTTP 400 confirme que l’authentification a réussi sans lire un article. Une réponse HTTP 401 indique un jeton absent ou incorrect ; HTTP 503 indique que le fichier de configuration serveur est absent. Ne pas tester en ouvrant l’endpoint dans un navigateur : celui-ci n’envoie pas le header secret.

Le transfert FTP suit `FTP_PLAIN` dans `.env.local`. Si `FTP_PLAIN=true`, FTP transmet le jeton sans chiffrement. Une variable `GRIMPEROOTS_WS_TOKEN` déjà exportée dans un terminal continue aussi de remplacer celle de `.env.local` : après rotation, exécuter `unset GRIMPEROOTS_WS_TOKEN` dans ce terminal ou l’actualiser. Ne jamais mettre le jeton dans une URL, le JSON de réponse ou un fichier versionné ; le `.htaccess` bloque aussi le téléchargement direct du fichier de configuration.

Les identifiants MySQL ne sont pas nécessaires dans `.env.local` : les endpoints PHP les lisent sur OVH dans `/www/j6/configuration.php`. Les variables `FTP_HOST`, `FTP_USER`, `FTP_PASSWORD`, `FTP_PLAIN` et `REMOTE_ROOT` servent uniquement au déploiement décrit ci-dessous. `J6_DB_*` n’est pas utilisé localement.

[`joomla_custom/ws_client.py`](joomla_custom/ws_client.py) est le client HTTP partagé par les outils de `joomla_custom/`. Il lit `SITE_URL` et `GRIMPEROOTS_WS_TOKEN` depuis `.env.local`, puis laisse les variables d’environnement du processus les remplacer si elles sont définies. `get_json()` envoie une requête HTTPS GET avec `Accept: application/json` et, pour les endpoints protégés, le secret dans le header `X-Grimperoots-Token`. Il vérifie le certificat TLS, refuse les redirections afin de ne pas transmettre le secret à une autre adresse, décode la réponse JSON et transforme les erreurs HTTP ou réseau en messages compréhensibles. Il ne déploie aucun fichier et ne fait aucune écriture sur Joomla.

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

### Démonstration de création d'article

[`create_article_demo.py`](joomla_api/create_article_demo.py) montre la création d'un article par `POST /api/index.php/v1/content/articles`, avec le token `JOOMLA_TOKEN`. L'article est explicitement créé non publié (`state: 0`). La simulation est le comportement par défaut ; `--apply` envoie réellement la requête et crée un nouvel article à chaque exécution. L'option facultative `--login` choisit l'auteur Joomla : le script résout le nom de connexion en ID avec une requête de lecture sur l'endpoint Users et inclut cet ID dans `created_by`.

```bash
python3 -m joomla_api.create_article_demo \
  --title "Démo API Joomla" \
  --category-id 33 \
  --text "Article de démonstration créé via le Web Service Joomla."
```

Inspecter le payload puis ajouter `--apply` pour créer le brouillon sur Joomla :

```bash
python3 -m joomla_api.create_article_demo \
  --title "Démo API Joomla" \
  --category-id 33 \
  --text "Article de démonstration créé via le Web Service Joomla." \
  --apply
```

Pour choisir un auteur, ajouter par exemple `--login orel` à la commande :

```bash
python3 -m joomla_api.create_article_demo --title "Démo API Joomla" --category-id 33 --text "Article de démonstration." --login orel
```

Avec `--login`, le token doit aussi avoir le droit de lire l'endpoint Users. Le compte associé au token doit avoir le droit de créer un article dans la catégorie choisie et de définir son auteur. Le script ne publie pas le brouillon et ne modifie aucun article existant. La simulation avec `--login` fait uniquement la lecture nécessaire pour résoudre le login ; elle n'envoie pas le POST de création.

### Démonstration de l'authentification HTTP Basic

[`basic_auth_demo.py`](joomla_api/basic_auth_demo.py) envoie une requête GET en lecture seule vers `GET /api/index.php/v1/users?page[limit]=1` en utilisant un compte Joomla existant. Le script impose HTTPS, vérifie le certificat du serveur, refuse les redirections et n'affiche pas les données utilisateur reçues.

**Prérequis :** le plugin Joomla **API Authentication - Basic** doit être installé et activé. Dans l'administration, ouvrir **Système → Gérer → Plugins**, rechercher ce nom et contrôler son état. Le compte doit aussi avoir le droit de se connecter à l'API et l'accès au composant Utilisateurs ; une réponse 401 invite à vérifier le plugin et les identifiants, tandis qu'une réponse 403 indique un problème de permissions.

Lancer la démo :

```bash
python3 -m joomla_api.basic_auth_demo
```

Le script lit `JOOMLA_BASE_URL` depuis `.env.local`, puis demande toujours le login et le mot de passe dans le terminal. Le mot de passe est saisi sans affichage ; les identifiants ne sont pas lus depuis un fichier et ne sont pas enregistrés par le script. On peut passer un autre fichier de configuration avec `--env-file chemin/vers/fichier`. Ne jamais inscrire ces identifiants dans une URL ou un fichier versionné.

HTTP Basic transmet les identifiants à chaque requête, encodés mais non chiffrés par lui-même : cette démo n'autorise donc que HTTPS. Joomla prend en charge cette méthode, mais recommande les jetons pour les intégrations habituelles ; la démo sert à vérifier l'authentification d'un compte existant. Elle ne protège pas les scripts PHP autonomes de `/media/`, qui ne passent pas par le dispatcher de l'API Joomla.

---

## 2. `joomla_custom/` — Endpoints complémentaires

Les endpoints versionnés sont dans `joomla_custom/www/ws/`. Sur l’hébergement actuel, leur destination est `/www/ws/`, à côté de l’installation Joomla `/www/j6/`. Ils chargent sa configuration depuis `/www/j6/configuration.php`.

### Déployer un endpoint PHP

`joomla_custom.deploy_ws` envoie un fichier PHP versionné de `joomla_custom/www/ws/` vers `/www/ws/` avec les accès FTP de `.env.local`. `REMOTE_ROOT` désigne `/www/j6` ; le script cible son dossier frère `/www/ws`. Le mode par défaut est une simulation. Toute transmission exige `--apply` ; si le fichier existe déjà, ajouter aussi `--overwrite`.

```bash
python3 -m joomla_custom.deploy_ws article-photos.php --dry-run
python3 -m joomla_custom.deploy_ws article-photos.php --apply
```

Le script vérifie le SHA-256 du fichier après transfert et ne déploie pas `config.local.php` ni les fichiers communs préfixés par `_`. FTPS est utilisé par défaut ; `FTP_PLAIN=true` force FTP sans chiffrement et ne doit être utilisé que si l’hébergement ne permet pas FTPS.

### Index des comptes rendus

[`cr-index.php`](joomla_custom/www/ws/cr-index.php) sélectionne les articles publiés de la catégorie racine `CRs` (ID 33) et de ses sous-catégories. Il renvoie uniquement l’ID, le titre et la date. Le JSON est utilisé par le client Python ; l’ouverture dans un navigateur affiche une table HTML :

[https://www.grimperoots.fr/ws/cr-index.php](https://www.grimperoots.fr/ws/cr-index.php)

Cet index est public et ne demande pas de jeton : il ne liste que des articles publiés et leurs métadonnées publiques. À l’inverse, `article.php` renvoie le texte brut complet et peut aussi retrouver un article non publié ; il exige donc `X-Grimperoots-Token`.

Le format se choisit directement dans l’URL :

- HTML : `https://www.grimperoots.fr/ws/cr-index.php?format=html`
- JSON : `https://www.grimperoots.fr/ws/cr-index.php?format=json`
- JSON d’une autre catégorie : `https://www.grimperoots.fr/ws/cr-index.php?category_id=14&format=json`

Le JSON a cette forme :

```json
{
  "data": [
    {"id": 802, "title": "Titre du compte rendu", "created": "2026-01-15 10:00:00"}
  ],
  "meta": {"count": 1}
}
```

On peut aussi préciser `Accept: application/json` à la requête HTTP. Sans choix de format, un navigateur reçoit le HTML et un client qui demande du JSON le reçoit en JSON.

Exporter localement la liste :

```bash
python3 -m joomla_custom.fetch_cr_index
```

Le fichier `data/cr_index.json` inclut une URL reconstruite à partir de l’ID. `--category-id` permet de choisir une autre catégorie et `--output` de modifier le fichier de sortie. `--dry-run` affiche la requête sans la lancer.

### Texte brut d’un article

[`article.php`](joomla_custom/www/ws/article.php) prend l’ID avec `?id=<ID>` et renvoie exclusivement du JSON ; il n’a pas de rendu HTML. Il récupère les champs `introtext` et `fulltext` stockés en base, ainsi que les tags. Il ne lance pas les plugins Joomla : une directive comme `{gallery}` est donc conservée. L’endpoint exige le header `X-Grimperoots-Token` ; l’ID seul ne permet pas de consulter le contenu brut.

Exemple d’appel direct avec `curl` depuis un terminal où `GRIMPEROOTS_WS_TOKEN` est défini :

```bash
curl --fail-with-body \
  -H "X-Grimperoots-Token: ${GRIMPEROOTS_WS_TOKEN}" \
  "https://www.grimperoots.fr/ws/article.php?id=802"
```

```bash
python3 -m joomla_custom.fetch_article 802
python3 -m joomla_custom.fetch_article 802 --output data/article-802.json
```

La sortie contient `id`, `title`, `alias`, `category_id`, `category`, `created`, `introtext`, `fulltext` et `existing_tags`. `--dry-run` simule la requête. L’ancien `--apply` reste accepté comme alias de compatibilité et ne provoque aucune écriture.

### Inventaire des photos d’un CR

[`article-photos.php`](joomla_custom/www/ws/article-photos.php) prend l’ID du CR avec `?id=<ID>` et renvoie du JSON. Il exige le même header `X-Grimperoots-Token` que `article.php` ; le secret ne doit être transmis ni dans une URL, ni dans un navigateur, ni dans la réponse. L’appel est destiné à un client serveur utilisant HTTPS.

L’endpoint lit les directives `{gallery}...{/gallery}` dans le contenu brut de l’article, ainsi que les images référencées par ses balises `<img>`. Il parcourt les fichiers image des répertoires de galerie correspondants sous `images/albums/`. Les chemins `path` et les valeurs de `galleries` sont relatifs à cette racine. Les chemins sont vérifiés contre la racine réelle du répertoire afin de bloquer les sorties de dossier ; seules les images existantes avec une extension reconnue sont ajoutées à `photos`. Les galeries sont parcourues récursivement. Une photo présente dans le contenu et une galerie est dédupliquée et conservée avec `type: "article"`.

Exemple de réponse :

```json
{
  "article_id": 797,
  "article_title": "Titre du CR",
  "article_date": "2026-04-26",
  "article_url": "https://www.grimperoots.fr/j6/797",
  "galleries": ["2026/coollover"],
  "photos": [
    {"type": "article", "path": "2026/coollover/coollover_0011.jpg"},
    {"type": "gallery", "path": "2026/coollover/coollover_0002.jpg"}
  ]
}
```

Le client construit les URL des photos en ajoutant le préfixe `https://www.grimperoots.fr/j6/images/albums/` aux chemins `path`.

Pour récupérer l’inventaire d’un CR en JSON :

```bash
python3 -m joomla_custom.fetch_article_photos 797
```

Le JSON est écrit sur la sortie standard. `--output` permet de l’enregistrer dans un fichier, et `--env-file` de choisir un autre fichier de configuration. Le programme lit le secret dans `.env.local`, le transmet dans le header HTTPS et ne l’affiche pas.

```bash
python3 -m joomla_custom.fetch_article_photos 797 --output data/article-797-photos.json
```

```bash
curl --fail-with-body \
  -H "X-Grimperoots-Token: ${GRIMPEROOTS_WS_TOKEN}" \
  "https://www.grimperoots.fr/ws/article-photos.php?id=797"
```

Ces endpoints exécutent uniquement des requêtes SQL `SELECT` et, pour l’inventaire des photos, lisent les fichiers sous `images/albums/`. Les outils Python les appellent en HTTPS et ne déposent plus de fichiers temporaires par FTP.

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
