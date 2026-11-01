from assistant import pii_eval
from assistant.pii import iban_ok, luhn_ok, mask
from assistant.text import detect_language, has_domain_term, normalize


def test_luhn_and_iban_checks():
    assert luhn_ok("4111111111111111")
    assert not luhn_ok("4111111111111112")
    assert iban_ok("FR76 3000 6000 0112 3456 7890 189")
    assert not iban_ok("FR76 3000 6000 0112 3456 7890 188")


def test_card_masked_with_last4_only():
    for raw in ("4111 1111 1111 1111", "4111-1111-1111-1111", "4111111111111111"):
        r = mask(f"ma carte {raw} est bloquée")
        assert "[CARTE ****1111]" in r.text and "4111" not in r.text.replace("****1111", "")


def test_invalid_16_digit_reference_is_not_a_card():
    assert mask("référence 4111111111111112").entities == []


def test_phone_email_rib_cin():
    r = mask("Appelez le +212 6 43 18 69 13 ou 0612345678, mail a.b@example.ma, RIB 011 780 0000123456789012 34, CIN BE123456")
    assert r.summary() == {"PHONE": 2, "EMAIL": 1, "RIB": 1, "CIN": 1}
    assert mask("voir l'article A07 du guide").entities == []  # pas de CIN sans mot-clé


def test_secrets_masked_but_not_ordinary_words():
    assert mask("mon code PIN est 1234").has_secret
    assert mask("mot de passe : Soleil2024!").has_secret
    assert not mask("mon PIN est bloqué").entities
    assert not mask("my password is wrong").entities


def test_amounts_and_dates_untouched():
    text = "J'ai payé 1 250,00 MAD le 12/10/2026 à 14h30"
    assert mask(text).text == text


def test_synthetic_set_non_regression():
    res = pii_eval.score(pii_eval.generate())
    assert res["ALL"]["recall"] == 1.0
    assert res["false_positives_on_negative_cases"] == 0


def test_language_detection_and_domain_gate():
    assert detect_language("Ma carte n'est toujours pas arrivée") == "fr"
    assert detect_language("My card still hasn't arrived") == "en"
    assert has_domain_term("virement en attente", "fr")
    assert not has_domain_term("donne-moi une recette de tajine", "fr")
    assert normalize("Débité deux fois !") == "debite deux fois"
