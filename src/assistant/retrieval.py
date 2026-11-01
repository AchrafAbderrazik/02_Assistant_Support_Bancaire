"""Base de connaissances et recherche hybride (BM25 + TF-IDF mots + TF-IDF caractères).

Chaque article existe en français et en anglais. Les documents indexés = titre + corps + mots-clés
(noms d'intentions pour l'anglais, lexique de synonymes pour le français).
En anglais, la recherche est combinée à la probabilité donnée par le classifieur d'intentions.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Okapi
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel

from .text import content_tokens, normalize, split_sentences

W_WORD, W_CHAR, W_BM25 = 0.45, 0.35, 0.20


@dataclass(frozen=True)
class Article:
    id: str
    intents: tuple[str, ...]
    tool: str | None
    sensitive: bool
    title: dict
    body: dict

    def text(self, lang: str) -> str:
        return f"{self.title[lang]}. {self.body[lang]}"


class KnowledgeBase:
    def __init__(self, articles: list[Article], bank: str, warning: str, fr_keywords: dict | None = None):
        self.articles = articles
        self.by_id = {a.id: a for a in articles}
        self.bank, self.warning = bank, warning
        self.intent_to_article = {i: a.id for a in articles for i in a.intents}
        self.fr_keywords = {k: v for k, v in (fr_keywords or {}).items() if not k.startswith("_")}
        self.indexes = {lang: _LangIndex(self._docs(lang), lang) for lang in ("fr", "en")}

    @classmethod
    def load(cls, kb_path: Path, lexicon_path: Path | None = None) -> "KnowledgeBase":
        raw = json.loads(Path(kb_path).read_text(encoding="utf-8"))
        arts = [
            Article(
                a["id"], tuple(a["intents"]), a.get("tool"), bool(a.get("sensitive")),
                {"fr": a["title_fr"], "en": a["title_en"]}, {"fr": a["body_fr"], "en": a["body_en"]},
            )
            for a in raw["articles"]
        ]
        kw = json.loads(Path(lexicon_path).read_text(encoding="utf-8")) if lexicon_path and Path(lexicon_path).exists() else {}
        return cls(arts, raw.get("bank", ""), raw.get("warning", ""), kw)

    def _docs(self, lang: str) -> list[str]:
        docs = []
        for a in self.articles:
            extra = " ".join(self.fr_keywords.get(a.id, [])) if lang == "fr" else " ".join(i.replace("_", " ") for i in a.intents)
            docs.append(f"{a.title[lang]} {a.title[lang]} {a.body[lang]} {extra}")
        return docs

    def search(self, query: str, lang: str, k: int = 3) -> list[tuple[str, float]]:
        scores = self.indexes[lang].scores(query)
        order = np.argsort(-scores)[:k]
        return [(self.articles[i].id, float(scores[i])) for i in order]

    def article_scores(self, query: str, lang: str) -> np.ndarray:
        return self.indexes[lang].scores(query)

    def article_proba_from_intents(self, intent_labels: list[str], proba: np.ndarray) -> np.ndarray:
        """Probabilité par article = somme des probabilités des intentions rattachées à l'article."""
        out = np.zeros(len(self.articles))
        pos = {a.id: i for i, a in enumerate(self.articles)}
        for label, p in zip(intent_labels, proba):
            out[pos[self.intent_to_article[label]]] += p
        return out

    def best_sentences(self, article_id: str, lang: str, query: str, n: int = 3) -> list[str]:
        """Sélection extractive : les phrases de l'article les plus proches de la question, dans l'ordre d'origine."""
        sents = split_sentences(self.by_id[article_id].body[lang])
        if len(sents) <= n:
            return sents
        vec = TfidfVectorizer(preprocessor=normalize, analyzer="char_wb", ngram_range=(3, 5)).fit(sents + [query])
        sims = linear_kernel(vec.transform([query]), vec.transform(sents))[0]
        keep = sorted(np.argsort(-sims)[:n])
        if 0 not in keep:  # la première phrase donne le contexte : on la garde
            keep = sorted([0] + keep[: n - 1])
        return [sents[i] for i in keep]


class _LangIndex:
    def __init__(self, docs: list[str], lang: str):
        self.lang = lang
        self.word = TfidfVectorizer(analyzer=lambda t: content_tokens(t, lang) + _bigrams(content_tokens(t, lang)), sublinear_tf=True)
        self.char = TfidfVectorizer(preprocessor=normalize, analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True)
        self.Xw = self.word.fit_transform(docs)
        self.Xc = self.char.fit_transform(docs)
        self.bm25 = BM25Okapi([content_tokens(d, lang) for d in docs])

    def scores(self, query: str) -> np.ndarray:
        sw = linear_kernel(self.word.transform([query]), self.Xw)[0]
        sc = linear_kernel(self.char.transform([query]), self.Xc)[0]
        b = np.asarray(self.bm25.get_scores(content_tokens(query, self.lang)), dtype=float)
        b = b / b.max() if b.max() > 0 else b
        return W_WORD * sw + W_CHAR * sc + W_BM25 * b


def _bigrams(toks: list[str]) -> list[str]:
    return [f"{a}_{b}" for a, b in zip(toks, toks[1:])]
