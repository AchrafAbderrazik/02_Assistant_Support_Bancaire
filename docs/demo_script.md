# Démonstration en 5 minutes

Préparation : `python -m assistant build` puis `python -m assistant serve`, ouvrir http://127.0.0.1:8000.

1. **Contexte (30 s)** — « Assistant de support d'une banque fictive : il répond seul quand il est sûr, appelle des
   outils, demande confirmation avant d'agir et transmet le reste à un conseiller. Données personnelles masquées. »
2. **Client C001 — « J'ai perdu ma carte »** → proposition de blocage (CONFIRM_ACTION) → bouton « oui » → ACTION_DONE.
   Montrer que rien n'est bloqué avant le « oui ».
3. **« Mon code PIN est 4821, il est bloqué »** → avertissement de sécurité ; sous la bulle : texte enregistré avec
   `[SECRET]`. Panneau de droite : données masquées = SECRET.
4. **Client C002 — « j'ai été débité deux fois au restaurant »** → opérations récentes, débit en double détecté,
   dossier transmis (panneau « Dossiers »).
5. **« j'ai une question sur ma carte »** → question de clarification avec 3 choix → choisir 1 → statut des cartes.
6. **Client C003 — « I forgot my PIN, what can I do? »** → réponse en anglais (classifieur) ; **« donne-moi une recette
   de tajine »** → hors périmètre.
7. **Évaluation (1 min)** — `reports/evaluation_report.md` et `reports/figures/risk_coverage.png` : 91,0 % d'exactitude
   sur 77 intentions, 99,2 % des requêtes traitées automatiquement à 95,5 % d'exactitude ; limites.

Plan B sans navigateur : `python -m assistant chat --customer C002`.
