"""Évaluation complète sur des données jamais vues pendant l'entraînement ni le réglage des seuils.

- Banking77 test officiel (3 080 requêtes réelles, anglais) : intentions, articles, prédiction sélective.
- Requêtes françaises rédigées par le développeur (sous-ensemble « test ») : recherche + seuil.
- Requêtes hors périmètre (FR et EN) : taux de rejet.
- Masquage des données personnelles (jeu synthétique), détection de langue, scénarios de bout en bout, latence.
"""
from __future__ import annotations

import json
import logging
import shutil
import statistics
import tempfile
import time
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, f1_score

from . import pii_eval
from .bankdb import BankTools, seed_database
from .config import Settings
from .intent import IntentModel, risk_coverage
from .retrieval import KnowledgeBase
from .service import AssistantService
from .store import ConversationStore
from .text import detect_language, has_domain_term
from .train import load_banking77

log = logging.getLogger("assistant.evaluate")


def _r(x, n=4):
    return None if x is None else round(float(x), n)


def eval_intents(model: IntentModel, kb: KnowledgeBase, svc: AssistantService, test: pd.DataFrame) -> dict:
    texts, gold = test["text"].tolist(), np.array(test["category"].tolist())
    t0 = time.perf_counter()
    proba = model.predict_proba(texts)
    batch_ms = (time.perf_counter() - t0) * 1000 / len(texts)
    labels = np.array(model.labels)
    top = np.argsort(-proba, axis=1)
    pred, conf = labels[top[:, 0]], proba.max(1)
    correct = pred == gold
    top3 = np.array([g in labels[t[:3]] for g, t in zip(gold, top)])
    acc_mask = conf >= model.threshold

    art_ids = np.array([a.id for a in kb.articles])
    gold_art = np.array([kb.intent_to_article[g] for g in gold])
    scores, _ = svc.article_scores_en(texts)
    art_pred, art_conf = art_ids[scores.argmax(1)], scores.max(1)
    art_correct = art_pred == gold_art
    art_acc_mask = art_conf >= svc.en_threshold
    clf_only = np.vstack([kb.article_proba_from_intents(model.labels, p) for p in proba])
    ret_only = np.vstack([kb.article_scores(t, "en") for t in texts])

    pairs = Counter((g, p) for g, p in zip(gold, pred) if g != p).most_common(12)
    f1s = f1_score(gold, pred, average=None, labels=model.labels)
    worst = sorted(zip(model.labels, f1s), key=lambda x: x[1])[:8]
    return {
        "test_size": len(texts),
        "intent": {
            "accuracy": _r(correct.mean()), "macro_f1": _r(f1_score(gold, pred, average="macro")),
            "top3_accuracy": _r(top3.mean()), "threshold": _r(model.threshold),
            "coverage": _r(acc_mask.mean()), "accepted_accuracy": _r(correct[acc_mask].mean()),
            "risk_coverage": risk_coverage(conf, correct),
            "top_confusions": [{"gold": g, "pred": p, "count": c} for (g, p), c in pairs],
            "worst_f1": [{"intent": i, "f1": _r(f)} for i, f in worst],
            "mean_predict_ms_batched": _r(batch_ms, 3),
        },
        "article": {
            "n_articles": len(kb.articles), "alpha": svc.alpha,
            "accuracy_hybrid": _r(art_correct.mean()),
            "accuracy_classifier_only": _r((art_ids[clf_only.argmax(1)] == gold_art).mean()),
            "accuracy_retrieval_only": _r((art_ids[ret_only.argmax(1)] == gold_art).mean()),
            "retrieval_only_hit3": _r(np.mean([g in art_ids[np.argsort(-s)[:3]] for g, s in zip(gold_art, ret_only)])),
            "threshold": _r(svc.en_threshold), "coverage": _r(art_acc_mask.mean()),
            "accepted_accuracy": _r(art_correct[art_acc_mask].mean()),
            "risk_coverage": risk_coverage(art_conf, art_correct),
        },
    }


def eval_french(svc: AssistantService, fr: pd.DataFrame) -> dict:
    out = {}
    for split in ("dev", "test"):
        s = fr[fr["split"] == split]
        ins, oos = s[s["expected"] != "OOS"], s[s["expected"] == "OOS"]
        ranks, accepted, acc_correct = [], [], []
        for text, exp in zip(ins["text"], ins["expected"]):
            ranking = svc.kb.search(text, "fr", k=21)
            ids = [a for a, _ in ranking]
            ranks.append(ids.index(exp) + 1)
            nlu = svc.understand(text, "fr")
            accepted.append(nlu.accepted)
            acc_correct.append(nlu.accepted and nlu.ranking[0][0] == exp)
        ranks = np.array(ranks)
        oos_rejected = [not svc.understand(t, "fr").accepted for t in oos["text"]]
        n_acc = int(np.sum(accepted))
        out[split] = {
            "in_scope": int(len(ins)), "out_of_scope": int(len(oos)),
            "hit1": _r((ranks == 1).mean()), "hit3": _r((ranks <= 3).mean()), "mrr": _r((1 / ranks).mean()),
            "coverage": _r(np.mean(accepted)), "accepted_accuracy": _r(np.sum(acc_correct) / n_acc) if n_acc else None,
            "oos_rejection_rate": _r(np.mean(oos_rejected)) if len(oos) else None,
        }
    out["threshold"] = _r(svc.fr_threshold)
    out["margin"] = _r(svc.fr_margin)
    return out


def eval_en_oos(svc: AssistantService, path: Path) -> dict:
    texts = pd.read_csv(path)["text"].tolist()
    res = [svc.understand(t, "en") for t in texts]
    return {"n": len(texts), "rejection_rate": _r(np.mean([not r.accepted for r in res])),
            "max_confidence": _r(max(r.confidence for r in res)), "threshold": _r(svc.en_threshold)}


SCENARIOS = [
    {"name": "Carte perdue (1 carte) : confirmation puis blocage", "customer": "C001",
     "turns": [("J'ai perdu ma carte", "CONFIRM_ACTION"), ("oui", "ACTION_DONE")], "check": ("card_status", "K101", "bloquée")},
    {"name": "Carte volée (2 cartes) : choix, puis refus -> rien n'est modifié", "customer": "C002",
     "turns": [("ma carte a été volée", "CHOOSE_CARD"), ("1", "CONFIRM_ACTION"), ("non", "ACTION_CANCELLED")],
     "check": ("card_status", "K201", "active")},
    {"name": "Lost card (EN) with card number: masked, then blocked", "customer": "C004",
     "turns": [("I lost my card 4111 1111 1111 1111", "CONFIRM_ACTION"), ("yes", "ACTION_DONE")],
     "check": ("card_status", "K401", "bloquée")},
    {"name": "Paiement en attente : outil opérations", "customer": "C001",
     "turns": [("Pourquoi mon paiement est encore en attente ?", "CALL_TOOL")], "check": ("tool", "list_recent_transactions", None)},
    {"name": "Débit en double : opérations + escalade", "customer": "C002",
     "turns": [("j'ai été débité deux fois au restaurant", "ESCALATE_HUMAN")], "check": ("duplicates", None, None)},
    {"name": "Virement en attente : outil virements", "customer": "C001",
     "turns": [("mon virement est en attente depuis deux jours", "CALL_TOOL")], "check": ("tool", "get_transfer_status", None)},
    {"name": "Forgot PIN (EN): documented answer", "customer": "C003",
     "turns": [("I forgot my PIN, what can I do?", "ANSWER_FROM_KB")], "check": ("article", "A06", None)},
    {"name": "Secret communiqué : masqué et non stocké", "customer": "C003",
     "turns": [("mon code PIN est 4821 et il ne marche plus", None)], "check": ("not_stored", "4821", None)},
    {"name": "Hors périmètre", "customer": "C001", "turns": [("donne-moi une recette de tajine", "OUT_OF_SCOPE")], "check": None},
    {"name": "Demande de conseiller", "customer": "C001",
     "turns": [("je veux parler à un conseiller", "ESCALATE_HUMAN")], "check": ("case", None, None)},
    {"name": "Question vague : clarification puis choix", "customer": "C001",
     "turns": [("j'ai une question sur ma carte", "ASK_CLARIFICATION"), ("1", "CALL_TOOL")],
     "check": ("article", "A01", None)},
    {"name": "Incertitude persistante : escalade après une clarification", "customer": "C001",
     "turns": [("problème avec mon compte", "ASK_CLARIFICATION"), ("toujours un problème avec mon compte", "ESCALATE_HUMAN")],
     "check": None},
    {"name": "Salutation", "customer": "C001", "turns": [("Bonjour", "GREETING")], "check": None},
]


def run_scenarios(settings: Settings, model: IntentModel, kb: KnowledgeBase) -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="assistant_scen_"))
    try:
        results = []
        for sc in SCENARIOS:
            db = tmp / f"bank_{len(results)}.db"
            seed_database(db)
            svc = AssistantService(settings, model=model, kb=kb, tools=BankTools(db),
                                   store=ConversationStore(tmp / f"conv_{len(results)}.db"))
            conv, ok, trace = None, True, []
            for msg, expected in sc["turns"]:
                r = svc.chat(sc["customer"], msg, conv)
                conv = r["conversation_id"]
                good = expected is None or r["action"] in expected.split("|")
                ok &= good
                trace.append({"message": r["masked_message"], "action": r["action"], "expected": expected, "ok": good})
            chk = sc.get("check")
            if chk and ok:
                kind, a, b = chk
                if kind == "card_status":
                    ok = next(c for c in svc.tools.get_card_status(sc["customer"])["cards"] if c["card_id"] == a)["status"] == b
                elif kind == "tool":
                    ok = (r.get("tool_result") or {}).get("tool") == a
                elif kind == "duplicates":
                    ok = bool((r.get("tool_result") or {}).get("possible_duplicates")) and bool(r.get("case_id"))
                elif kind == "article":
                    ok = (r.get("article") or {}).get("id") == a
                elif kind == "not_stored":
                    ok = all(a not in m["text_masked"] for m in svc.store.transcript(conv)) and "[SECRET]" in r["masked_message"]
                elif kind == "case":
                    ok = bool(r.get("case_id"))
            results.append({"name": sc["name"], "passed": bool(ok), "trace": trace})
        return {"n": len(results), "passed": sum(r["passed"] for r in results), "scenarios": results}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def measure_latency(settings: Settings, model: IntentModel, kb: KnowledgeBase, texts: list[str]) -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="assistant_lat_"))
    try:
        seed_database(tmp / "bank.db")
        svc = AssistantService(settings, model=model, kb=kb, tools=BankTools(tmp / "bank.db"),
                               store=ConversationStore(tmp / "conv.db"))
        svc.chat("C001", "warm-up")
        lat = []
        for t in texts:
            t0 = time.perf_counter()
            svc.chat("C001", t)
            lat.append((time.perf_counter() - t0) * 1000)
        q = np.percentile(lat, [50, 95])
        return {"n_messages": len(lat), "p50_ms": _r(q[0], 1), "p95_ms": _r(q[1], 1), "mean_ms": _r(statistics.mean(lat), 1)}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def figures(metrics: dict, out_dir: Path) -> list[str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_dir.mkdir(parents=True, exist_ok=True)
    names = []
    fig, ax = plt.subplots(figsize=(6.4, 4.2), dpi=130)
    for key, label, color in (("intent", "Intention (77 classes)", "#1f5f8b"), ("article", "Article de la base (21)", "#c0612b")):
        rc = metrics["banking77_test"][key]["risk_coverage"]
        ax.plot([p["coverage"] for p in rc], [p["accuracy"] for p in rc], label=label, color=color, lw=2)
        m = metrics["banking77_test"][key]
        ax.scatter([m["coverage"]], [m["accepted_accuracy"]], color=color, zorder=3)
    ax.axhline(0.95, color="#888", ls="--", lw=1)
    ax.set_xlabel("Couverture (part des requêtes traitées automatiquement)")
    ax.set_ylabel("Exactitude sur les requêtes traitées")
    ax.set_title("Banking77 (test) : exactitude selon la couverture\n(points = seuils appris sur la validation)", fontsize=10)
    ax.set_ylim(0.88, 1.0)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, loc="lower left")
    fig.tight_layout()
    fig.savefig(out_dir / "risk_coverage.png")
    plt.close(fig)
    names.append("risk_coverage.png")

    conf = metrics["banking77_test"]["intent"]["top_confusions"][:10][::-1]
    fig, ax = plt.subplots(figsize=(7.2, 4.2), dpi=130)
    ax.barh([f"{c['gold']} → {c['pred']}" for c in conf], [c["count"] for c in conf], color="#1f5f8b")
    ax.set_xlabel("Nombre d'erreurs (test)")
    ax.set_title("Confusions les plus fréquentes (intention réelle → prédite)", fontsize=10)
    ax.tick_params(axis="y", labelsize=7)
    fig.tight_layout()
    fig.savefig(out_dir / "top_confusions.png")
    plt.close(fig)
    names.append("top_confusions.png")
    return names


def evaluate_all(settings: Settings) -> dict:
    settings.ensure_dirs()
    model = IntentModel.load(settings.model_path)
    kb = KnowledgeBase.load(settings.kb_path, settings.lexicon_path)
    _, test = load_banking77(settings)
    fr = pd.read_csv(settings.eval_dir / "fr_queries.csv")
    tmp = Path(tempfile.mkdtemp(prefix="assistant_eval_"))
    try:
        seed_database(tmp / "bank.db")
        svc = AssistantService(settings, model=model, kb=kb, tools=BankTools(tmp / "bank.db"),
                               store=ConversationStore(tmp / "conv.db"))
        metrics = {
            "model": {k: model.meta.get(k) for k in ("selected_kind", "candidates", "fit_size", "valid_size",
                                                     "hybrid_alpha", "alpha_valid_article_accuracy", "fr_dev", "versions")},
            "banking77_test": eval_intents(model, kb, svc, test),
            "french": eval_french(svc, fr),
            "en_out_of_scope": eval_en_oos(svc, settings.eval_dir / "en_out_of_scope.csv"),
            "language_detection": {
                "en_banking77_test_accuracy": _r(np.mean([detect_language(t) == "en" for t in test["text"]])),
                "fr_queries_accuracy": _r(np.mean([detect_language(t) == "fr" for t in fr["text"]])),
            },
            "domain_gate": {"en_banking77_test_pass_rate": _r(np.mean([has_domain_term(t, "en") for t in test["text"]]))},
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    cases = pii_eval.generate()
    metrics["pii"] = pii_eval.score(cases)
    metrics["scenarios"] = run_scenarios(settings, model, kb)
    sample = test.sample(150, random_state=1)["text"].tolist() + fr[fr["expected"] != "OOS"]["text"].tolist()[:50]
    metrics["latency_chat"] = measure_latency(settings, model, kb, sample)
    metrics["figures"] = figures(metrics, settings.reports_dir / "figures")
    (settings.reports_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    (settings.reports_dir / "evaluation_report.md").write_text(render_report(metrics), encoding="utf-8")
    return metrics


def _pct(x, n=1) -> str:
    if x is None:
        return "n/a"
    return f"{x * 100:.{n}f}".replace(".", ",") + " %"


def _num(x, n=3) -> str:
    return "n/a" if x is None else f"{x:.{n}f}".replace(".", ",")


def render_report(m: dict) -> str:
    b, a, fr = m["banking77_test"]["intent"], m["banking77_test"]["article"], m["french"]
    cands = m["model"]["candidates"]
    lines = [
        "# Rapport d'évaluation — assistant de support bancaire",
        "",
        "Toutes les valeurs ci-dessous sont produites par `python -m assistant evaluate` (fichier `reports/metrics.json`).",
        "Les seuils sont appris sur la validation (10 % de l'entraînement Banking77) ou sur le sous-ensemble « dev »",
        "des requêtes françaises ; les chiffres « test » n'ont servi à aucun réglage.",
        "",
        "## 1. Classification d'intentions — Banking77, jeu de test officiel",
        "",
        f"Requêtes de test : {m['banking77_test']['test_size']} (anglais, 77 intentions).",
        "",
        "| Modèle (validation) | Exactitude | F1 macro | Entraînement |",
        "|---|---|---|---|",
    ]
    for k, v in cands.items():
        lines.append(f"| {k} | {_pct(v['valid_accuracy'])} | {_num(v['valid_macro_f1'])} | {_num(v['fit_seconds'], 1)} s |")
    lines += [
        "",
        f"Modèle retenu : **{m['model']['selected_kind']}** (meilleure exactitude de validation).",
        "",
        "| Mesure (test) | Valeur |",
        "|---|---|",
        f"| Exactitude (intention) | {_pct(b['accuracy'])} |",
        f"| F1 macro | {_num(b['macro_f1'])} |",
        f"| Exactitude top-3 | {_pct(b['top3_accuracy'])} |",
        f"| Prédiction sélective — seuil {_num(b['threshold'])} : couverture | {_pct(b['coverage'])} |",
        f"| Exactitude sur les requêtes acceptées | {_pct(b['accepted_accuracy'])} |",
        "",
        "## 2. Choix de l'article de la base de connaissances (anglais)",
        "",
        f"21 articles couvrent les 77 intentions. Pondération classifieur / recherche α = {a['alpha']} (choisie sur la validation).",
        "",
        "| Mesure (test) | Valeur |",
        "|---|---|",
        f"| Exactitude — classifieur seul | {_pct(a['accuracy_classifier_only'])} |",
        f"| Exactitude — recherche seule (BM25 + TF-IDF) | {_pct(a['accuracy_retrieval_only'])} (top-3 : {_pct(a['retrieval_only_hit3'])}) |",
        f"| Exactitude — combinaison retenue | {_pct(a['accuracy_hybrid'])} |",
        f"| Seuil {_num(a['threshold'])} : part traitée automatiquement | {_pct(a['coverage'])} |",
        f"| Exactitude sur les requêtes traitées automatiquement | {_pct(a['accepted_accuracy'])} |",
        "",
        "Les requêtes non traitées automatiquement reçoivent une question de clarification puis, si besoin, une escalade.",
        "",
        "## 3. Requêtes en français (recherche hybride sur la base française)",
        "",
        "Jeu rédigé par le développeur (117 requêtes, dont 12 hors périmètre) : **mesure indicative**, pas une estimation",
        "de performance en production. Le lexique de synonymes n'a été ajusté qu'à partir du sous-ensemble « dev ».",
        "",
        "| Sous-ensemble | Requêtes | Top-1 | Top-3 | MRR | Couverture | Exactitude acceptées | Rejet hors périmètre |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for s in ("dev", "test"):
        f = fr[s]
        lines.append(f"| {s} | {f['in_scope']} + {f['out_of_scope']} HP | {_pct(f['hit1'])} | {_pct(f['hit3'])} | {_num(f['mrr'])} | "
                     f"{_pct(f['coverage'])} | {_pct(f['accepted_accuracy'])} | {_pct(f['oos_rejection_rate'])} |")
    eo, ld, pii = m["en_out_of_scope"], m["language_detection"], m["pii"]
    lines += [
        "",
        f"Seuil français : score ≥ {_num(fr['threshold'])} et écart avec le 2e article ≥ {_num(fr['margin'], 2)}.",
        "",
        "## 4. Hors périmètre, langue, masquage",
        "",
        f"- Requêtes anglaises hors périmètre (10, rédigées par le développeur) rejetées : {_pct(eo['rejection_rate'])}.",
        f"- Détection de langue : anglais (Banking77 test) {_pct(ld['en_banking77_test_accuracy'])} ; "
        f"français (requêtes FR) {_pct(ld['fr_queries_accuracy'])}.",
        f"- Masquage (jeu **synthétique** de {pii['n_cases']} messages, dont {pii['n_negative_cases']} pièges sans donnée "
        f"personnelle) : précision {_pct(pii['ALL']['precision'])}, rappel {_pct(pii['ALL']['recall'])}, "
        f"faux positifs sur les pièges : {pii['false_positives_on_negative_cases']}. C'est un test de non-régression : "
        "les noms de personnes et les adresses ne sont pas détectés (limite connue).",
        "",
        "## 5. Scénarios de bout en bout",
        "",
        f"{m['scenarios']['passed']} / {m['scenarios']['n']} scénarios réussis (API interne, bases temporaires).",
        "",
        "| Scénario | Résultat | Actions obtenues |",
        "|---|---|---|",
    ]
    for sc in m["scenarios"]["scenarios"]:
        acts = " → ".join(t["action"] for t in sc["trace"])
        lines.append(f"| {sc['name']} | {'réussi' if sc['passed'] else 'ÉCHEC'} | {acts} |")
    lat = m["latency_chat"]
    lines += [
        "",
        "## 6. Latence (processeur local, un tour de conversation complet)",
        "",
        f"{lat['n_messages']} messages : médiane {_num(lat['p50_ms'], 1)} ms, 95e centile {_num(lat['p95_ms'], 1)} ms.",
        "",
        "## 7. Erreurs les plus fréquentes (intentions)",
        "",
        "| Intention réelle | Prédite | Nombre |",
        "|---|---|---|",
    ]
    for c in b["top_confusions"][:8]:
        lines.append(f"| {c['gold']} | {c['pred']} | {c['count']} |")
    lines += [
        "",
        "Ces confusions concernent surtout des intentions voisines (souvent rattachées au même article), ce qui explique",
        "que l'exactitude au niveau article soit plus élevée qu'au niveau intention.",
        "",
        "## 8. Limites",
        "",
        "- Classifieur entraîné en anglais uniquement (Banking77) ; le français passe par la recherche documentaire.",
        "- Base de connaissances et données clients fictives : les réponses illustrent le fonctionnement, pas une offre réelle.",
        "- Pas de modèle génératif évalué : les réponses sont extraites de la base (aucune information inventée).",
        "- Le jeu français et les jeux hors périmètre sont petits et rédigés par le développeur.",
        "",
    ]
    return "\n".join(lines)
