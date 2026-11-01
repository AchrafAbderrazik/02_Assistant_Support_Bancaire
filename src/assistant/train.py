"""Entraînement du classifieur et apprentissage des seuils (sur validation uniquement, jamais sur le test)."""
from __future__ import annotations

import hashlib
import json
import logging
import platform

import numpy as np
import pandas as pd
import sklearn
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import train_test_split

from .config import SEED, TARGET_ACCEPTED_ACCURACY, VALIDATION_FRACTION, Settings
from .intent import IntentModel, choose_threshold
from .retrieval import KnowledgeBase
from .text import has_domain_term

log = logging.getLogger("assistant.train")
ALPHAS = (1.0, 0.9, 0.8, 0.7, 0.6, 0.5)
MARGINS = (0.0, 0.02, 0.04, 0.06, 0.08, 0.10)


def sha256(path) -> str:
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def load_banking77(settings: Settings) -> tuple[pd.DataFrame, pd.DataFrame]:
    train = pd.read_csv(settings.raw_dir / "train.csv")
    test = pd.read_csv(settings.raw_dir / "test.csv")
    for df in (train, test):
        df["text"] = df["text"].astype(str).str.strip()
    return train, test


def split_train_valid(train: pd.DataFrame, seed: int = SEED):
    return train_test_split(train["text"].tolist(), train["category"].tolist(), test_size=VALIDATION_FRACTION,
                            stratify=train["category"], random_state=seed)


def article_scores(model: IntentModel, kb: KnowledgeBase, texts: list[str], alpha: float) -> np.ndarray:
    proba = model.predict_proba(texts)
    art = np.vstack([kb.article_proba_from_intents(model.labels, p) for p in proba])
    if alpha < 1.0:
        ret = np.vstack([kb.article_scores(t, "en") for t in texts])
        return alpha * art + (1 - alpha) * ret
    return art


def fr_threshold_from_dev(kb: KnowledgeBase, dev: pd.DataFrame) -> tuple[float, float, dict]:
    """Seuil de score (tau) puis marge minimale entre les deux premiers articles (mu), appris sur « dev »."""
    conf, margin, correct = [], [], []
    for text, expected in zip(dev["text"], dev["expected"]):
        (top, s1), (_, s2) = kb.search(text, "fr", 2)
        gate = has_domain_term(text, "fr")
        conf.append(s1 if gate else 0.0)
        margin.append(s1 - s2)
        correct.append(expected != "OOS" and top == expected)
    conf, margin, correct = np.array(conf), np.array(margin), np.array(correct)
    tau = choose_threshold(conf, correct, TARGET_ACCEPTED_ACCURACY, min_support=10)
    best = (0.0, -1.0)
    for mu in MARGINS:  # précision maximale, puis marge la plus petite (couverture maximale)
        acc = (conf >= tau) & (margin >= mu)
        precision = correct[acc].mean() if acc.any() else 0.0
        if precision > best[1] + 1e-9:
            best = (mu, precision)
    mu = best[0]
    acc = (conf >= tau) & (margin >= mu)
    return tau, mu, {"dev_size": int(len(dev)), "dev_coverage": float(acc.mean()),
                     "dev_accepted_accuracy": float(correct[acc].mean()) if acc.any() else None}


def train_all(settings: Settings, kinds: tuple[str, ...] = ("logreg", "svm_calibrated")) -> tuple[IntentModel, dict]:
    settings.ensure_dirs()
    train, _ = load_banking77(settings)
    kb = KnowledgeBase.load(settings.kb_path, settings.lexicon_path)
    x_fit, x_val, y_fit, y_val = split_train_valid(train)
    y_val_arr = np.array(y_val)

    candidates = {}
    for kind in kinds:
        m = IntentModel.train(x_fit, y_fit, kind=kind)
        pred, conf = m.predict(x_val)
        candidates[kind] = {
            "model": m,
            "valid_accuracy": float(accuracy_score(y_val, pred)),
            "valid_macro_f1": float(f1_score(y_val, pred, average="macro")),
            "fit_seconds": m.meta["fit_seconds"],
        }
        log.info("%s : exactitude validation %.4f, F1 macro %.4f (%.1f s)", kind,
                 candidates[kind]["valid_accuracy"], candidates[kind]["valid_macro_f1"], m.meta["fit_seconds"])
    best_kind = max(candidates, key=lambda k: candidates[k]["valid_accuracy"])
    model = candidates[best_kind]["model"]

    # seuil au niveau intention (rapporté) et au niveau article (utilisé par l'assistant)
    pred, conf = model.predict(x_val)
    tau_intent = choose_threshold(conf, np.array(pred) == y_val_arr, TARGET_ACCEPTED_ACCURACY)
    gold_art = np.array([kb.intent_to_article[y] for y in y_val])
    art_ids = np.array([a.id for a in kb.articles])
    alpha_scores = {}
    for alpha in ALPHAS:
        s = article_scores(model, kb, x_val, alpha)
        alpha_scores[alpha] = (float((art_ids[s.argmax(1)] == gold_art).mean()), s)
    best_alpha = max(ALPHAS, key=lambda a: (round(alpha_scores[a][0], 4), a))
    s = alpha_scores[best_alpha][1]
    tau_article = choose_threshold(s.max(1), art_ids[s.argmax(1)] == gold_art, TARGET_ACCEPTED_ACCURACY)

    fr = pd.read_csv(settings.eval_dir / "fr_queries.csv")
    tau_fr, mu_fr, fr_info = fr_threshold_from_dev(kb, fr[fr["split"] == "dev"])

    model.threshold = tau_intent
    model.meta.update({
        "selected_kind": best_kind,
        "candidates": {k: {kk: vv for kk, vv in v.items() if kk != "model"} for k, v in candidates.items()},
        "fit_size": len(x_fit), "valid_size": len(x_val),
        "intent_threshold": tau_intent,
        "hybrid_alpha": best_alpha,
        "alpha_valid_article_accuracy": {str(a): round(v[0], 4) for a, v in alpha_scores.items()},
        "en_article_threshold": tau_article,
        "fr_threshold": tau_fr, "fr_margin": mu_fr, "fr_dev": fr_info,
        "target_accepted_accuracy": TARGET_ACCEPTED_ACCURACY,
        "data_sha256": {"train.csv": sha256(settings.raw_dir / "train.csv"), "test.csv": sha256(settings.raw_dir / "test.csv")},
        "versions": {"python": platform.python_version(), "scikit-learn": sklearn.__version__},
        "seed": SEED,
    })
    model.save(settings.model_path)
    summary = {k: v for k, v in model.meta.items()}
    (settings.reports_dir / "training_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("modèle retenu : %s ; alpha=%.1f ; seuils intention=%.3f article=%.3f FR=%.3f",
             best_kind, best_alpha, tau_intent, tau_article, tau_fr)
    return model, summary
