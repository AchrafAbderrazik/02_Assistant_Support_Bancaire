import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from assistant.api import create_app
from assistant.generator import OllamaRewriter, numbers_supported


def _status(service, customer, card):
    return next(c for c in service.tools.get_card_status(customer)["cards"] if c["card_id"] == card)["status"]


def test_lost_card_blocked_only_after_confirmation(service):
    r = service.chat("C001", "J'ai perdu ma carte")
    assert r["action"] == "CONFIRM_ACTION" and _status(service, "C001", "K101") == "active"
    r = service.chat("C001", "oui", r["conversation_id"])
    assert r["action"] == "ACTION_DONE" and _status(service, "C001", "K101") == "bloquée"
    with sqlite3.connect(service.tools.db_path) as con:
        assert con.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'block_card'").fetchone()[0] == 1


def test_choice_then_refusal_changes_nothing(service):
    r = service.chat("C002", "ma carte a été volée")
    assert r["action"] == "CHOOSE_CARD" and len(r["options"]) == 2
    r = service.chat("C002", "1", r["conversation_id"])
    r = service.chat("C002", "non", r["conversation_id"])
    assert r["action"] == "ACTION_CANCELLED" and _status(service, "C002", "K201") == "active"


def test_expired_confirmation_is_not_executed(service):
    r = service.chat("C001", "J'ai perdu ma carte")
    conv = r["conversation_id"]
    _, state = service.store.get_or_create(conv, "C001")
    state["pending"]["expires_at"] = time.time() - 1
    service.store.save_state(conv, state)
    r = service.chat("C001", "oui", conv)
    assert r["action"] == "ACTION_CANCELLED" and _status(service, "C001", "K101") == "active"


def test_raw_secrets_and_card_numbers_never_stored(service):
    r = service.chat("C004", "My card 4111 1111 1111 1111 was stolen and my PIN is 4821")
    log = " ".join(m["text_masked"] for m in service.store.transcript(r["conversation_id"]))
    assert "4111 1111" not in log and "4821" not in log and "****1111" in log
    assert "never share your PIN" in r["reply"]


def test_other_customer_cannot_reuse_conversation(service):
    r = service.chat("C001", "Bonjour")
    with pytest.raises(PermissionError):
        service.chat("C002", "bonjour", r["conversation_id"])


def test_dispute_is_escalated_with_transactions(service):
    r = service.chat("C002", "j'ai été débité deux fois au restaurant")
    assert r["action"] == "ESCALATE_HUMAN" and r["case_id"] and r["tool_result"]["possible_duplicates"]


def test_llm_rewriter_falls_back_and_guards_numbers():
    rw = OllamaRewriter("http://127.0.0.1:9", "absent", timeout=0.5)  # aucun serveur : repli sur le gabarit
    assert rw.rewrite("fr", "question", "Délai indicatif : 5 à 10 jours.") is None
    assert numbers_supported("entre 5 et 10 jours", "Délai : 5 à 10 jours")
    assert not numbers_supported("sous 3 jours", "Délai : 5 à 10 jours")


def test_api_endpoints(project, service):
    settings, _, _ = project
    client = TestClient(create_app(settings, service))
    assert client.get("/api/health").json()["status"] == "ok"
    assert len(client.get("/api/customers").json()["customers"]) == 4
    r = client.post("/api/chat", json={"customer_id": "C001", "message": "Pourquoi mon paiement est encore en attente ?"})
    assert r.status_code == 200 and r.json()["action"] == "CALL_TOOL"
    conv = r.json()["conversation_id"]
    assert client.get(f"/api/conversations/{conv}", params={"customer_id": "C001"}).status_code == 200
    assert client.get(f"/api/conversations/{conv}", params={"customer_id": "C002"}).status_code == 403
    assert client.post("/api/chat", json={"customer_id": "X1", "message": "hi"}).status_code == 422
    assert client.post("/api/chat", json={"customer_id": "C001", "message": ""}).status_code == 422
    assert client.post("/api/chat", json={"customer_id": "C999", "message": "hello"}).status_code == 404
    assert client.get("/").status_code == 200
