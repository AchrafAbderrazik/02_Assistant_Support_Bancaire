# Décisions techniques (et alternatives écartées)

| Décision | Pourquoi | Alternatives envisagées |
|---|---|---|
| Banking77 pour l'entraînement et le test | Requêtes réelles, annotées, licence ouverte, résultats comparables | Données synthétiques (pas crédibles) ; données d'une banque (confidentielles) |
| TF-IDF + régression logistique | Rapide (CPU), explicable, 91 % d’exactitude ; aucun GPU ni service payant | Modèle Transformer affiné (généralement plus précis sur ce jeu, mais lourd et non téléchargeable dans l’environnement de développement) |
| Prédiction sélective (seuils) | En banque, mieux vaut clarifier ou escalader que se tromper avec assurance | Répondre toujours (top-1) |
| Seuils au niveau **article** | L'assistant répond avec des articles : une confusion entre deux intentions du même article n'est pas une erreur pour le client | Seuil au niveau intention (couverture 92 % au lieu de 99 %) |
| Recherche hybride BM25 + TF-IDF pour le français | Le classifieur ne connaît que l'anglais ; la base française permet de répondre en français sans traduction | Traduction automatique (modèle indisponible hors ligne) ; embeddings multilingues (non téléchargeables ici) |
| Garde-fou « termes du périmètre » | Évite de répondre au hasard à une question hors sujet | Seuil seul (chevauchement des scores observé sur le « dev ») |
| Réponses extractives | Aucune invention : chaque phrase vient de la base, la source est citée | Génération libre par LLM (risque d'hallucination sur des délais ou montants) |
| LLM local optionnel avec contrôle des chiffres | Montre l'intégration possible sans dépendre d'une API payante ; tout nombre absent du contexte entraîne un retour au gabarit | API distante (coût, données qui sortent) |
| Politique déterministe | Lisible, testable, auditable | Agent LLM qui choisit les outils (moins prévisible pour des actions sensibles) |
| Confirmation explicite + expiration (5 min) + audit pour le blocage | Action irréversible : consentement clair, traçabilité | Blocage direct |
| Identité du client issue de la session, jamais du message | Empêche d'agir sur le compte d'un autre client | Lire un identifiant dans le texte |
| Journal SQLite du texte masqué uniquement | Minimisation des données (principe de la loi 09-08 et du RGPD) | Journaliser le texte brut |
| FastAPI | Validation Pydantic, documentation OpenAPI automatique | Flask (utilisé dans le projet de ponctualité, pour varier) |
