# Fiche des données

## 1. Banking77 (réel, public)
- 13 083 requêtes en anglais (10 003 entraînement, 3 080 test), 77 intentions, licence CC BY 4.0 (`data/raw/SOURCES.md`).
- Découpage : 90 % de l'entraînement pour ajuster le modèle (9 002), 10 % stratifiés pour la validation (1 001 ; choix du
  modèle, des pondérations et des seuils). Le test officiel ne sert qu'à l'évaluation finale.
- Particularités : deux noms d'intentions atypiques dans la source (`reverted_card_payment?`, `Refund_not_showing_up`),
  conservés tels quels ; des intentions très proches (ex. `card_arrival` / `card_delivery_estimate`).

## 2. Base de connaissances (rédigée pour le projet)
- 21 articles en français et en anglais (`data/kb/articles.json`) pour une banque fictive, la « Banque Démo ».
- Chaque intention Banking77 est rattachée à exactement un article (77 → 21), avec l'outil associé et un indicateur
  « sensible » (carte perdue ou volée, opération contestée, vérification d'identité).
- Les délais et montants cités sont des **exemples** et ne décrivent aucune banque réelle.

## 3. Lexique français (rédigé pour le projet)
- Synonymes et formulations courantes par article (`data/lexicon/fr_keywords.json`), utilisés par la recherche française.
- Ajusté **uniquement** à partir des erreurs du sous-ensemble « dev » des requêtes françaises.

## 4. Requêtes d'évaluation rédigées par le développeur
- `data/eval/fr_queries.csv` : 117 requêtes françaises (105 dans le périmètre, 12 hors périmètre), réparties en « dev »
  (46) et « test » (71). Formulations variées, fautes et absence d'accents incluses.
- `data/eval/en_out_of_scope.csv` : 10 requêtes anglaises hors périmètre.
- Biais assumé : l'auteur des requêtes est aussi l'auteur du lexique ; ces mesures sont **indicatives**.

## 5. Données bancaires simulées
- Générées par `python -m assistant seed` (graine 42, date de référence 15/10/2026) : 4 clients, 6 cartes,
  126 opérations, 8 virements ; noms « Client démo 1 » à « Client démo 4 » ; commerçants suffixés « (démo) ».
- Cas de démonstration volontaires : débit en double (client 2), carte en livraison (client 2), carte bientôt expirée
  et carte virtuelle (client 3), paiement annulé, virements en attente ou échoués.

## 6. Jeu synthétique de masquage
- Généré par `assistant/pii_eval.py` (graine 7) : 168 messages, dont 84 sans donnée personnelle mais avec des pièges
  (montants, dates, références de 16 chiffres invalides, « mon PIN est bloqué »).
- Numéros aléatoires (cartes valides selon Luhn, IBAN valides selon le modulo 97) ne correspondant à personne.
