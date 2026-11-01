import pytest

from assistant.policy import NLU, decide, decide_pending, is_greeting, wants_human


def _nlu(article, accepted=True, in_domain=True):
    return NLU("fr", [(article, 0.5), ("A01", 0.2), ("A02", 0.1)], 0.5, accepted, in_domain, "test")


def test_decisions(project):
    _, _, kb = project
    get = kb.by_id.__getitem__
    assert decide(_nlu("A03"), get, 0).action == "CHOOSE_CARD"           # blocage -> confirmation obligatoire
    assert decide(_nlu("A07"), get, 0).action == "ESCALATE_HUMAN"        # contestation -> conseiller
    assert decide(_nlu("A14"), get, 0).action == "CALL_TOOL"             # outil en lecture seule
    assert decide(_nlu("A06"), get, 0).action == "ANSWER_FROM_KB"
    assert decide(_nlu("A06", accepted=False), get, 0).action == "ASK_CLARIFICATION"
    assert decide(_nlu("A06", accepted=False), get, 1).action == "ESCALATE_HUMAN"
    assert decide(_nlu("A06", accepted=False, in_domain=False), get, 0).action == "OUT_OF_SCOPE"


def test_pending_steps():
    assert decide_pending("oui", {"kind": "confirm_block"}).action == "ACTION_DONE"
    assert decide_pending("Non merci", {"kind": "confirm_block"}).action == "ACTION_CANCELLED"
    assert decide_pending("et mes frais ?", {"kind": "confirm_block"}) is None
    assert decide_pending("2", {"kind": "choose_card", "options": ["K1", "K2"]}).choice == 1
    assert decide_pending("5", {"kind": "choose_card", "options": ["K1", "K2"]}) is None
    assert wants_human("je veux parler à un conseiller") and not wants_human("quelqu'un utilise ma carte")
    assert is_greeting("Bonjour") and not is_greeting("Bonjour, ma carte est bloquée depuis hier")


def test_tools_isolate_customers(service):
    with pytest.raises(PermissionError):
        service.tools.block_card("C001", "K201", "test")  # carte d'un autre client
    assert service.tools.list_recent_transactions("C002")["possible_duplicates"]
    assert len(service.tools.list_recent_transactions("C001", limit=999)["transactions"]) == 20
