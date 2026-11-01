# API REST

Base : `http://127.0.0.1:8000` (`python -m assistant serve`). Documentation interactive : `/docs`.

| Méthode | Chemin | Entrée | Sortie |
|---|---|---|---|
| GET | `/api/health` | — | état, modèle, seuils |
| GET | `/api/customers` | — | clients fictifs |
| POST | `/api/chat` | `customer_id` (C000), `message` (1–1 000 car.), `conversation_id` (option), `lang` (option : fr, en) | réponse, action, article, confiance, options, résultat d'outil, dossier, données masquées, latence |
| GET | `/api/conversations/{id}?customer_id=C001` | — | transcription **masquée** (403 si autre client) |
| GET | `/api/cases?limit=50` | — | dossiers transmis à un conseiller |
| GET | `/api/stats` | — | nombre de conversations, réponses par action |
| GET | `/api/metrics` | — | métriques d'évaluation (après `python -m assistant evaluate`) |

Actions possibles : `GREETING`, `ANSWER_FROM_KB`, `CALL_TOOL`, `CHOOSE_CARD`, `CONFIRM_ACTION`, `ACTION_DONE`,
`ACTION_CANCELLED`, `ASK_CLARIFICATION`, `ESCALATE_HUMAN`, `OUT_OF_SCOPE`.

Codes d'erreur : 400 (message invalide côté service), 403 (ressource d'un autre client), 404 (client inconnu),
422 (validation Pydantic).

```bash
curl -s -X POST http://127.0.0.1:8000/api/chat -H "Content-Type: application/json" \
  -d '{"customer_id":"C002","message":"mon virement est en attente depuis deux jours"}'
# {"action": "CALL_TOOL", "article": {"id": "A14", ...}, "tool_result": {"tool": "get_transfer_status", ...}, ...}
```
