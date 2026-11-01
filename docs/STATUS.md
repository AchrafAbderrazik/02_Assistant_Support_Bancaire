# État d'avancement (30/10/2026)

## Implémenté et testé
- Masquage (7 types d'entités + avertissement sur les secrets) — jeu synthétique 100 % / 0 faux positif sur les pièges.
- Classifieur d'intentions anglais (Banking77) avec sélection de modèle et seuils appris sur la validation.
- Recherche hybride FR/EN, garde-fou de périmètre, marge d'ambiguïté apprise sur le « dev » français.
- Politique déterministe ; outils sur base simulée ; blocage de carte avec choix, confirmation, expiration et audit.
- API FastAPI, interface web (vérifiée dans Chromium, aucune erreur de console), journal masqué, dossiers d'escalade.
- 24 tests pytest réussis ; 13 / 13 scénarios ; rapport d'évaluation et figures générés.

## Implémenté mais NON évalué
- Reformulation par LLM local (Ollama) : code et garde-fou présents, testés uniquement en l'absence de serveur
  (retour au gabarit) ; aucun modèle n'a été exécuté dans le cadre de ce projet.

## Non fait / pistes
- Classifieur français entraîné sur de vraies requêtes ; embeddings multilingues.
- Authentification réelle, chiffrement, politique de conservation, limitation du débit.
- Détection des noms et adresses (NER) ; tableau de bord de suivi (taux d'escalade, dérive).
- Conteneurisation (Docker) et intégration continue.
