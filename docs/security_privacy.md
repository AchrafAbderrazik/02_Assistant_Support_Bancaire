# Sécurité et données personnelles

## Ce qui est fait
1. **Masquage avant tout traitement** : le texte brut ne sert qu'à produire le texte masqué ; la classification, la
   recherche, le journal et les réponses n'utilisent que le texte masqué. Test : `test_raw_secrets_and_card_numbers_never_stored`.
2. **Secrets** (PIN, CVV, code reçu par SMS, mot de passe) : masqués, jamais stockés, et un avertissement explique au
   client de ne pas les communiquer et de les changer ou de bloquer sa carte.
3. **Numéros de carte** : seuls les 4 derniers chiffres sont conservés (pratique courante d'affichage).
4. **Actions** : seul le blocage de carte modifie des données ; il exige une confirmation explicite (« oui »), expire
   après 5 minutes et est inscrit dans un journal d'audit.
5. **Isolation des clients** : les outils reçoivent l'identifiant du client de la session ; une carte ou une conversation
   d'un autre client est refusée (`PermissionError` → HTTP 403).
6. **Validation des entrées** : identifiant client au format `C000`, message de 1 à 1 000 caractères, identifiant de
   conversation hexadécimal ; requêtes SQL paramétrées ; limites sur le nombre de lignes renvoyées.
7. **Aucun secret dans le code** ; le mode LLM est désactivé par défaut et ne contacte qu'une adresse locale configurée.

## Ce qui n'est pas fait (à prévoir pour un usage réel)
- Authentification réelle (jeton de session, OAuth2) : ici le client « connecté » est simulé par un champ de requête.
- Chiffrement de la base, rotation et durée de conservation des journaux, droit à l'effacement.
- Détection des noms et adresses (modèle de reconnaissance d'entités nommées).
- Limitation du débit, journal d'accès, tests de sécurité (injection de prompt si un LLM est activé).
