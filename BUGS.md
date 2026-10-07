# Bugs connus

## HTTP 500 après mise à jour d'un article par l'API Joomla

**Statut :** cause identifiée ; correction serveur/plugin à vérifier.

Sur l'instance observée le 8 octobre 2026 : Joomla 6.1.4 et JComments 5.0.6. Les requêtes `PATCH /api/index.php/v1/content/articles/{id}` enregistrent les tags demandés, puis répondent HTTP 500.

Le journal Joomla `administrator/logs/everything.php` contient l'erreur suivante pour le CR 795 (00:34:04, heure de Paris) :

```text
Uncaught Throwable of type Error:
Call to undefined method Joomla\CMS\Router\ApiRouter::build()
```

La trace montre cette séquence :

1. Joomla enregistre la ligne de l'article dans `AdminModel::save()` avec `$table->store()`.
2. Joomla déclenche ensuite l'événement `onContentAfterSave`.
3. Le plugin `Content - JComments` appelle `JCommentsObject::storeObjectInfo()`.
4. Le code JComments de `components/com_jcomments/plugins/com_content.plugin.php` appelle `Route::_()` pour fabriquer le lien de l'article.
5. En contexte API, Joomla sélectionne `ApiRouter`, qui ne fournit pas `build()`. L'exception interrompt le callback avant `JCommentsModelObject::setObjectInfo()`.

La même incompatibilité de `Route::_()` avec le routeur API est décrite dans le [ticket Joomla #47662](https://issues.joomla.org/tracker/joomla-cms/47662), qui propose un repli vers le routeur du site.

### Impact observé

- Les relectures API après les PATCH ont confirmé les tags finaux sur les huit articles traités.
- Le PATCH du classificateur n'envoie que l'ID et la liste des tags ; l'article existant est chargé avant son enregistrement. Rien dans cette trace n'indique une altération du texte du compte rendu.
- Le callback échoue pendant le rafraîchissement des métadonnées JComments de l'article, avant l'appel qui les écrit. Les lignes des commentaires ne sont pas modifiées par ce chemin de code ; aucune perte de commentaire n'a été observée.
- L'horodatage `modified` de l'article est actualisé lors du PATCH.
- Une réponse HTTP 500 ne signifie donc pas, à elle seule, que les tags n'ont pas été enregistrés. `apply.py` relit l'article après une erreur pour vérifier son état.

### Suivi

Le warning dans `apply.py --apply` rappelle cet incident sans bloquer l’opération. Depuis l’analyse, le lot de neuf changements validés puis l’ajout de `Via Ferrata` au CR 600 ont été appliqués ; chaque PATCH a répondu HTTP 500, mais la relecture API a confirmé les tags finaux. Les métadonnées JComments de ces nouveaux articles n’ont pas été vérifiées. Les prochains changements de tags peuvent continuer après dry-run, à condition de traiter comme échec toute relecture inaccessible ou inattendue. Une correction du callback reste souhaitable pour supprimer les HTTP 500 et permettre à JComments de rafraîchir ses métadonnées.
