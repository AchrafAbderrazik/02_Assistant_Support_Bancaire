# Rapport d'évaluation — assistant de support bancaire

Toutes les valeurs ci-dessous sont produites par `python -m assistant evaluate` (fichier `reports/metrics.json`).
Les seuils sont appris sur la validation (10 % de l'entraînement Banking77) ou sur le sous-ensemble « dev »
des requêtes françaises ; les chiffres « test » n'ont servi à aucun réglage.

## 1. Classification d'intentions — Banking77, jeu de test officiel

Requêtes de test : 3080 (anglais, 77 intentions).

| Modèle (validation) | Exactitude | F1 macro | Entraînement |
|---|---|---|---|
| logreg | 92,0 % | 0,921 | 25,0 s |
| svm_calibrated | 91,5 % | 0,917 | 5,6 s |

Modèle retenu : **logreg** (meilleure exactitude de validation).

| Mesure (test) | Valeur |
|---|---|
| Exactitude (intention) | 91,0 % |
| F1 macro | 0,910 |
| Exactitude top-3 | 97,5 % |
| Prédiction sélective — seuil 0,451 : couverture | 92,0 % |
| Exactitude sur les requêtes acceptées | 94,7 % |

## 2. Choix de l'article de la base de connaissances (anglais)

21 articles couvrent les 77 intentions. Pondération classifieur / recherche α = 0.8 (choisie sur la validation).

| Mesure (test) | Valeur |
|---|---|
| Exactitude — classifieur seul | 95,1 % |
| Exactitude — recherche seule (BM25 + TF-IDF) | 66,5 % (top-3 : 85,0 %) |
| Exactitude — combinaison retenue | 95,0 % |
| Seuil 0,248 : part traitée automatiquement | 99,2 % |
| Exactitude sur les requêtes traitées automatiquement | 95,5 % |

Les requêtes non traitées automatiquement reçoivent une question de clarification puis, si besoin, une escalade.

## 3. Requêtes en français (recherche hybride sur la base française)

Jeu rédigé par le développeur (117 requêtes, dont 12 hors périmètre) : **mesure indicative**, pas une estimation
de performance en production. Le lexique de synonymes n'a été ajusté qu'à partir du sous-ensemble « dev ».

| Sous-ensemble | Requêtes | Top-1 | Top-3 | MRR | Couverture | Exactitude acceptées | Rejet hors périmètre |
|---|---|---|---|---|---|---|---|
| dev | 42 + 4 HP | 92,9 % | 97,6 % | 0,955 | 92,9 % | 100,0 % | 75,0 % |
| test | 63 + 8 HP | 90,5 % | 100,0 % | 0,950 | 96,8 % | 90,2 % | 100,0 % |

Seuil français : score ≥ 0,311 et écart avec le 2e article ≥ 0,02.

## 4. Hors périmètre, langue, masquage

- Requêtes anglaises hors périmètre (10, rédigées par le développeur) rejetées : 100,0 %.
- Détection de langue : anglais (Banking77 test) 99,5 % ; français (requêtes FR) 100,0 %.
- Masquage (jeu **synthétique** de 168 messages, dont 84 pièges sans donnée personnelle) : précision 100,0 %, rappel 100,0 %, faux positifs sur les pièges : 0. C'est un test de non-régression : les noms de personnes et les adresses ne sont pas détectés (limite connue).

## 5. Scénarios de bout en bout

13 / 13 scénarios réussis (API interne, bases temporaires).

| Scénario | Résultat | Actions obtenues |
|---|---|---|
| Carte perdue (1 carte) : confirmation puis blocage | réussi | CONFIRM_ACTION → ACTION_DONE |
| Carte volée (2 cartes) : choix, puis refus -> rien n'est modifié | réussi | CHOOSE_CARD → CONFIRM_ACTION → ACTION_CANCELLED |
| Lost card (EN) with card number: masked, then blocked | réussi | CONFIRM_ACTION → ACTION_DONE |
| Paiement en attente : outil opérations | réussi | CALL_TOOL |
| Débit en double : opérations + escalade | réussi | ESCALATE_HUMAN |
| Virement en attente : outil virements | réussi | CALL_TOOL |
| Forgot PIN (EN): documented answer | réussi | ANSWER_FROM_KB |
| Secret communiqué : masqué et non stocké | réussi | ANSWER_FROM_KB |
| Hors périmètre | réussi | OUT_OF_SCOPE |
| Demande de conseiller | réussi | ESCALATE_HUMAN |
| Question vague : clarification puis choix | réussi | ASK_CLARIFICATION → CALL_TOOL |
| Incertitude persistante : escalade après une clarification | réussi | ASK_CLARIFICATION → ESCALATE_HUMAN |
| Salutation | réussi | GREETING |

## 6. Latence (processeur local, un tour de conversation complet)

200 messages : médiane 9,1 ms, 95e centile 13,5 ms.

## 7. Erreurs les plus fréquentes (intentions)

| Intention réelle | Prédite | Nombre |
|---|---|---|
| unable_to_verify_identity | verify_my_identity | 5 |
| virtual_card_not_working | get_disposable_virtual_card | 5 |
| balance_not_updated_after_bank_transfer | transfer_not_received_by_recipient | 5 |
| card_payment_wrong_exchange_rate | wrong_exchange_rate_for_cash_withdrawal | 4 |
| why_verify_identity | unable_to_verify_identity | 4 |
| top_up_failed | top_up_reverted | 4 |
| card_arrival | card_delivery_estimate | 3 |
| fiat_currency_support | exchange_via_app | 3 |

Ces confusions concernent surtout des intentions voisines (souvent rattachées au même article), ce qui explique
que l'exactitude au niveau article soit plus élevée qu'au niveau intention.

## 8. Limites

- Classifieur entraîné en anglais uniquement (Banking77) ; le français passe par la recherche documentaire.
- Base de connaissances et données clients fictives : les réponses illustrent le fonctionnement, pas une offre réelle.
- Pas de modèle génératif évalué : les réponses sont extraites de la base (aucune information inventée).
- Le jeu français et les jeux hors périmètre sont petits et rédigés par le développeur.
