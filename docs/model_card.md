# Fiche modèle — classifieur d'intentions et décision

## Usage prévu
Router les questions de clients d'une banque (démonstration) vers le bon article, le bon outil ou un conseiller.
**Hors usage** : décision financière, détection de fraude, conseil, toute utilisation sur de vrais clients sans
validation complémentaire.

## Modèle
- Représentation : TF-IDF mots (unigrammes + bigrammes) et TF-IDF caractères (2 à 5, `char_wb`), texte normalisé
  (minuscules, sans accents).
- Candidats comparés sur la validation : régression logistique (C = 20) **retenue** — exactitude 92,0 %, F1 macro 0,921,
  entraînement ≈ 26 s ; SVM linéaire calibré (Platt, 3 plis) — 91,5 %, 0,917, ≈ 6 s.
- Niveau article : probabilité d'un article = somme des probabilités de ses intentions ; combinaison
  0,8 × classifieur + 0,2 × recherche (α choisi sur la validation : 94,5 % contre 94,3 % pour le classifieur seul).
  Sur le test, la combinaison n'apporte pas de gain (95,0 % contre 95,1 %) : résultat rapporté tel quel.

## Seuils (appris sur la validation, jamais sur le test)
- Article (anglais) : 0,248 → objectif 95 % d'exactitude sur les réponses automatiques.
- Intention : 0,451 (rapporté pour information).
- Français : score de recherche ≥ 0,311 **et** écart avec le 2e article ≥ 0,02 **et** au moins un terme du périmètre.
  Sur le « dev » français, toutes les erreurs avaient un écart < 0,01 et toutes les bonnes réponses un écart ≥ 0,10.

## Résultats sur le test (voir `reports/evaluation_report.md`)
Intention 91,0 % ; article 95,0 % ; 99,2 % des requêtes traitées automatiquement avec 95,5 % d'exactitude.
Français (indicatif) : top-1 90,5 %, top-3 100 %.

## Erreurs typiques (test)
Les confusions les plus fréquentes concernent des intentions voisines : `unable_to_verify_identity` → `verify_my_identity`
(5), `virtual_card_not_working` → `get_disposable_virtual_card` (5), `balance_not_updated_after_bank_transfer` →
`transfer_not_received_by_recipient` (5), `top_up_failed` → `top_up_reverted` (4). Les deux intentions sont souvent
rattachées au même article (identité, cartes virtuelles, recharges), d'où l'écart entre exactitude intention et article ;
la confusion entre virement « non crédité » et « non reçu par le bénéficiaire » change en revanche d'article.

## Limites et risques
- Anglais uniquement pour le classifieur ; pas d'évaluation sur de vraies conversations françaises.
- Pas de détection des noms ni des adresses dans le masquage.
- Les seuils dépendent de la distribution des données : à recalibrer sur des données réelles.
- Les requêtes hors périmètre anglaises ont une confiance maximale de 0,23, proche du seuil 0,248 : marge faible.
