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
- Le PATCH envoyé par `apply.py` ne contient que l'ID et la liste des tags ; l'article existant est chargé avant son enregistrement. Rien dans cette trace n'indique une altération du texte du compte rendu.
- Le callback échoue pendant le rafraîchissement des métadonnées JComments de l'article, avant l'appel qui les écrit. Les lignes des commentaires ne sont pas modifiées par ce chemin de code ; aucune perte de commentaire n'a été observée.
- L'horodatage `modified` de l'article est actualisé lors du PATCH.
- Une réponse HTTP 500 ne signifie donc pas, à elle seule, que les tags n'ont pas été enregistrés. `apply.py` relit l'article après une erreur pour vérifier son état.
- L'erreur fatale peut aussi interrompre le contrôleur API avant son appel `checkin()` : l'article reste alors verrouillé par le compte API (`admin`). Une tentative ultérieure peut échouer avec HTTP 400 et « The user checking out does not match the user who checked out the item ». Désactiver le plugin ne libère pas les verrous déjà laissés ; ceux-ci doivent être check-in dans l'administration Joomla.

### Suivi

Par défaut, `apply.py --apply` désactive temporairement le plugin `Content - Comments` (ID Joomla 10005) via le Web Services API, puis le réactive à la fin dans son état initial. `--keep-jcomments-enabled` permet de contourner ce comportement. Cette mesure évite l'erreur pour les prochaines écritures, mais les verrous existants doivent d'abord être libérés dans l'administration Joomla. La correction du callback reste souhaitable pour que JComments rafraîchisse ses métadonnées sans erreur.
