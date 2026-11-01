"""Classification d'intentions (anglais, 77 classes Banking77) avec probabilités calibrées.

Deux modèles comparés sur un jeu de validation stratifié (10 % de l'entraînement) :
- régression logistique sur TF-IDF mots (1-2) + caractères (2-5) ;
- SVM linéaire calibré (Platt, validation croisée à 3 plis) sur les mêmes représentations.
Le seuil de confiance (prédiction sélective) est choisi sur la validation pour viser 95 % d'exactitude
sur les requêtes traitées automatiquement ; les autres sont clarifiées ou escaladées.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import joblib
import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.svm import LinearSVC

from .text import normalize


def _features() -> FeatureUnion:
    return FeatureUnion(
        [
            ("word", TfidfVectorizer(preprocessor=normalize, ngram_range=(1, 2), sublinear_tf=True, min_df=1)),
            (
                "char",
                TfidfVectorizer(preprocessor=normalize, analyzer="char_wb", ngram_range=(2, 5), sublinear_tf=True, min_df=2),
            ),
        ]
    )


def build_pipeline(kind: str, seed: int = 42) -> Pipeline:
    if kind == "logreg":
        clf = LogisticRegression(C=20.0, max_iter=3000)
    elif kind == "svm_calibrated":
        clf = CalibratedClassifierCV(LinearSVC(C=0.5, random_state=seed), method="sigmoid", cv=3)
    else:
        raise ValueError(f"modèle inconnu : {kind}")
    return Pipeline([("features", _features()), ("clf", clf)])


def choose_threshold(confidence: np.ndarray, correct: np.ndarray, target: float = 0.95, min_support: int = 50) -> float:
    """Plus petit seuil (couverture maximale) tel que l'exactitude des prédictions acceptées atteigne la cible."""
    order = np.argsort(-confidence)
    conf_sorted, corr_sorted = confidence[order], correct[order].astype(float)
    cum_acc = np.cumsum(corr_sorted) / np.arange(1, len(corr_sorted) + 1)
    best = None
    for k in range(min_support, len(conf_sorted) + 1):
        if cum_acc[k - 1] >= target:
            best = k
    if best is None:
        return float(conf_sorted[min_support - 1])
    return float(conf_sorted[best - 1])


def risk_coverage(confidence: np.ndarray, correct: np.ndarray, points: int = 50) -> list[dict]:
    order = np.argsort(-confidence)
    corr = correct[order].astype(float)
    n = len(corr)
    out = []
    for k in np.unique(np.linspace(1, n, points).astype(int)):
        out.append({"coverage": k / n, "accuracy": float(corr[:k].mean()), "threshold": float(confidence[order][k - 1])})
    return out


@dataclass
class IntentModel:
    pipeline: Pipeline
    labels: list[str]
    threshold: float = 0.5
    meta: dict = field(default_factory=dict)

    @classmethod
    def train(cls, texts: list[str], labels: list[str], kind: str = "logreg", seed: int = 42) -> "IntentModel":
        t0 = time.perf_counter()
        pipe = build_pipeline(kind, seed)
        pipe.fit(texts, labels)
        classes = list(pipe.classes_)
        return cls(pipe, classes, meta={"kind": kind, "train_size": len(texts), "fit_seconds": round(time.perf_counter() - t0, 1)})

    def predict_proba(self, texts: list[str]) -> np.ndarray:
        return self.pipeline.predict_proba(texts)

    def predict(self, texts: list[str]) -> tuple[list[str], np.ndarray]:
        proba = self.predict_proba(texts)
        idx = proba.argmax(axis=1)
        return [self.labels[i] for i in idx], proba.max(axis=1)

    def top_k(self, text: str, k: int = 3) -> list[tuple[str, float]]:
        proba = self.predict_proba([text])[0]
        idx = np.argsort(-proba)[:k]
        return [(self.labels[i], float(proba[i])) for i in idx]

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"pipeline": self.pipeline, "labels": self.labels, "threshold": self.threshold, "meta": self.meta}, path)

    @classmethod
    def load(cls, path: Path) -> "IntentModel":
        obj = joblib.load(path)
        return cls(obj["pipeline"], obj["labels"], obj["threshold"], obj.get("meta", {}))
