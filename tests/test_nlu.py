import numpy as np

from assistant.intent import choose_threshold


def test_classifier_predicts_and_probabilities_sum_to_one(project):
    _, model, _ = project
    proba = model.predict_proba(["My card still hasn't arrived, what should I do?"])[0]
    assert abs(proba.sum() - 1) < 1e-6
    assert model.top_k("My card still hasn't arrived, what should I do?", 1)[0][0] in {"card_arrival", "card_delivery_estimate"}


def test_threshold_reaches_target_on_known_data():
    conf = np.linspace(1, 0, 200)
    correct = np.r_[np.ones(150, bool), np.zeros(50, bool)]
    tau = choose_threshold(conf, correct, target=0.95)
    accepted = conf >= tau
    assert correct[accepted].mean() >= 0.95 and accepted.sum() >= 150


def test_knowledge_base_covers_all_intents_in_both_languages(project):
    _, model, kb = project
    assert set(model.labels) == set(kb.intent_to_article)
    assert all(a.title["fr"] and a.body["en"] for a in kb.articles)


def test_french_retrieval_examples(project):
    _, _, kb = project
    assert kb.search("j'ai perdu ma carte, que faire ?", "fr", 1)[0][0] == "A03"
    assert kb.search("quel taux de change pour payer en euros ?", "fr", 1)[0][0] == "A10"


def test_extractive_sentences_come_from_article_in_order(project):
    _, _, kb = project
    sents = kb.best_sentences("A08", "fr", "paiement en attente", n=3)
    body = kb.by_id["A08"].body["fr"]
    assert 1 <= len(sents) <= 3 and all(s in body for s in sents)
    assert [body.index(s) for s in sents] == sorted(body.index(s) for s in sents)
