"""Orchestration d'un tour de conversation : masquage -> langue -> compréhension -> politique -> outils -> réponse."""
from __future__ import annotations

import time

import numpy as np

from .bankdb import BankTools
from .config import CONFIRMATION_TTL_SECONDS, MAX_MESSAGE_CHARS, Settings
from .generator import T, OllamaRewriter, card_label, compose_answer, format_tool, notices
from .intent import IntentModel
from .pii import mask
from .policy import NLU, YES_RE, Decision, decide, decide_pending, is_greeting, wants_human
from .retrieval import KnowledgeBase
from .store import ConversationStore
from .text import detect_language, has_domain_term, normalize


class AssistantService:
    def __init__(self, settings: Settings, model: IntentModel | None = None, kb: KnowledgeBase | None = None,
                 tools: BankTools | None = None, store: ConversationStore | None = None):
        self.settings = settings
        self.kb = kb or KnowledgeBase.load(settings.kb_path, settings.lexicon_path)
        self.model = model or IntentModel.load(settings.model_path)
        self.tools = tools or BankTools(settings.bank_db)
        self.store = store or ConversationStore(settings.conv_db)
        meta = self.model.meta
        self.alpha = float(meta.get("hybrid_alpha", 1.0))
        self.en_threshold = float(meta.get("en_article_threshold", 0.5))
        self.fr_threshold = float(meta.get("fr_threshold", 0.35))
        self.fr_margin = float(meta.get("fr_margin", 0.0))
        self.rewriter = (OllamaRewriter(settings.ollama_url, settings.ollama_model, settings.ollama_timeout)
                         if settings.llm_backend == "ollama" else None)

    # --- compréhension -------------------------------------------------------------------
    def article_scores_en(self, texts: list[str]) -> tuple[np.ndarray, np.ndarray]:
        """Scores par article (anglais) : alpha * P(article | classifieur) + (1 - alpha) * score de recherche."""
        proba = self.model.predict_proba(texts)
        art_p = np.vstack([self.kb.article_proba_from_intents(self.model.labels, p) for p in proba])
        if self.alpha < 1.0:
            ret = np.vstack([self.kb.article_scores(t, "en") for t in texts])
            return self.alpha * art_p + (1 - self.alpha) * ret, proba
        return art_p, proba

    def understand(self, text: str, lang: str) -> NLU:
        in_domain = has_domain_term(text, lang)
        if lang == "en":
            scores, proba = self.article_scores_en([text])
            scores, proba = scores[0], proba[0]
            order = np.argsort(-scores)
            ranking = [(self.kb.articles[i].id, float(scores[i])) for i in order[:3]]
            conf = float(scores[order[0]])
            return NLU("en", ranking, conf, conf >= self.en_threshold, in_domain, "classifieur + recherche",
                       self.model.labels[int(proba.argmax())])
        scores = self.kb.article_scores(text, "fr")
        order = np.argsort(-scores)
        ranking = [(self.kb.articles[i].id, float(scores[i])) for i in order[:3]]
        conf = float(scores[order[0]])
        margin = conf - float(scores[order[1]])
        accepted = conf >= self.fr_threshold and margin >= self.fr_margin and in_domain
        return NLU("fr", ranking, conf, accepted, in_domain, "recherche hybride")

    # --- un tour de conversation -----------------------------------------------------------
    def chat(self, customer_id: str, message: str, conversation_id: str | None = None, lang: str | None = None) -> dict:
        t0 = time.perf_counter()
        message = (message or "").strip()
        if not message or len(message) > MAX_MESSAGE_CHARS:
            raise ValueError(f"le message doit contenir entre 1 et {MAX_MESSAGE_CHARS} caractères")
        if not self.tools.customer_exists(customer_id):
            raise LookupError("client inconnu")
        conv_id, state = self.store.get_or_create(conversation_id, customer_id)
        masked = mask(message, "fr")
        lang = lang or detect_language(masked.text)
        masked = mask(message, lang)
        text = masked.text

        decision, nlu, expired = None, None, False
        pending = state.get("pending")
        if pending and time.time() > pending.get("expires_at", 0):
            state.pop("pending", None)
            expired, pending = bool(YES_RE.match(normalize(text))), None
        if pending:
            decision = decide_pending(text, pending)
            if decision is not None and pending.get("kind") == "clarify":
                state.pop("pending", None)
        if decision is None:
            pending = state.pop("pending", None) if not expired else None
            if expired:
                decision = Decision("ACTION_CANCELLED", reason="confirmation expirée")
            elif wants_human(text):
                decision = Decision("ESCALATE_HUMAN", reason="demande explicite d'un conseiller")
            elif is_greeting(text):
                decision = Decision("GREETING")
            else:
                nlu = self.understand(text, lang)
                decision = decide(nlu, self.kb.by_id.__getitem__, int(state.get("clarify_count", 0)))

        out = self._execute(decision, customer_id, conv_id, state, lang, text, pending, expired)
        parts = notices(lang, masked.types, masked.has_secret) + [out["reply"]]
        reply = "\n\n".join(p for p in parts if p)
        generator = "gabarit extractif"
        if self.rewriter and out["action"] in ("ANSWER_FROM_KB", "CALL_TOOL"):
            rewritten = self.rewriter.rewrite(lang, text, reply)
            generator = f"ollama:{self.settings.ollama_model}" if rewritten else "gabarit extractif (repli)"
            reply = rewritten or reply
        latency = round((time.perf_counter() - t0) * 1000, 1)

        art = self.kb.by_id.get(out.get("article_id") or "")
        meta = dict(lang=lang, action=out["action"], article_id=art.id if art else None,
                    intent=nlu.intent if nlu else None, confidence=round(nlu.confidence, 4) if nlu else None)
        self.store.log(conv_id, "user", text, lang=lang, pii_types=masked.types)
        self.store.log(conv_id, "assistant", reply, latency_ms=latency, **meta)
        self.store.save_state(conv_id, state)
        return {
            "conversation_id": conv_id, "reply": reply, "action": out["action"], "lang": lang,
            "article": {"id": art.id, "title": art.title[lang]} if art else None,
            "intent": meta["intent"], "confidence": meta["confidence"], "method": nlu.method if nlu else "règle",
            "accepted": nlu.accepted if nlu else None, "options": out.get("options", []),
            "tool_result": out.get("tool_result"), "case_id": out.get("case_id"),
            "pii": {"types": masked.types, "count": len(masked.entities)}, "masked_message": text,
            "reason": decision.reason, "generator": generator, "latency_ms": latency,
        }

    def _execute(self, d: Decision, customer_id: str, conv_id: str, state: dict, lang: str, text: str,
                 pending: dict | None, expired: bool) -> dict:
        t = T[lang]
        art = self.kb.by_id.get(d.article_id) if d.article_id else None

        if d.action == "GREETING":
            return {"action": "GREETING", "reply": t["greeting"]}

        if d.action in ("ANSWER_FROM_KB", "CALL_TOOL"):
            state["clarify_count"] = 0
            if d.action == "ANSWER_FROM_KB" and art.tool and art.tool != "block_card" and not art.sensitive:
                d = Decision("CALL_TOOL", art.id, reason=f"outil en lecture : {art.tool}")
            if art.tool == "block_card" or (art.sensitive and art.tool):  # choix issu d'une clarification
                return self._execute(Decision("CHOOSE_CARD" if art.tool == "block_card" else "ESCALATE_HUMAN", art.id,
                                              reason=d.reason), customer_id, conv_id, state, lang, text, None, False)
            tool_result = self.tools.run(art.tool, customer_id) if d.action == "CALL_TOOL" else None
            body = compose_answer(lang, art, self.kb.best_sentences(art.id, lang, text), format_tool(tool_result, lang))
            return {"action": d.action, "reply": body, "article_id": art.id, "tool_result": tool_result}

        if d.action == "ESCALATE_HUMAN":
            state["clarify_count"] = 0
            case_id = self.store.open_case(conv_id, customer_id, d.reason)
            if art:  # contestation : on montre les opérations récentes puis on transmet
                tool_result = self.tools.run(art.tool, customer_id) if art.tool else None
                body = compose_answer(lang, art, self.kb.best_sentences(art.id, lang, text, n=2), format_tool(tool_result, lang))
                return {"action": "ESCALATE_HUMAN", "article_id": art.id, "tool_result": tool_result, "case_id": case_id,
                        "reply": body + "\n\n" + t["escalate_dispute"].format(case=case_id)}
            return {"action": "ESCALATE_HUMAN", "reply": t["escalate"].format(case=case_id), "case_id": case_id}

        if d.action == "CHOOSE_CARD":
            cards = self.tools.blockable_cards(customer_id)
            intro = self.kb.best_sentences(art.id, lang, text, n=1)[0]
            if not cards:
                return {"action": "ESCALATE_HUMAN", "article_id": art.id,
                        "case_id": self.store.open_case(conv_id, customer_id, "blocage impossible : aucune carte active"),
                        "reply": intro + "\n\n" + t["no_card"]}
            if len(cards) == 1:
                return self._ask_confirmation(cards[0], state, lang, art.id, intro)
            opts = [{"n": i + 1, "label": card_label(c, lang), "card_id": c["card_id"]} for i, c in enumerate(cards)]
            state["pending"] = {"kind": "choose_card", "options": [c["card_id"] for c in cards], "article_id": art.id,
                                "expires_at": time.time() + CONFIRMATION_TTL_SECONDS}
            listing = "\n".join(f"{o['n']}. {o['label']}" for o in opts)
            return {"action": "CHOOSE_CARD", "article_id": art.id, "options": opts,
                    "reply": f"{intro}\n\n{t['choose_card']}\n{listing}"}

        if d.action == "CONFIRM_ACTION":
            card_id = pending["options"][d.choice]
            card = next(c for c in self.tools.blockable_cards(customer_id) if c["card_id"] == card_id)
            return self._ask_confirmation(card, state, lang, pending.get("article_id"), None)

        if d.action == "ACTION_DONE":
            state.pop("pending", None)
            res = self.tools.block_card(customer_id, pending["card_id"], reason="perte, vol ou fraude déclarés via l'assistant")
            label = pending["card_label"]
            msg = t["blocked" if res["changed"] else "already_blocked"].format(card=label)
            return {"action": "ACTION_DONE", "reply": msg, "tool_result": res, "article_id": pending.get("article_id")}

        if d.action == "ACTION_CANCELLED":
            state.pop("pending", None)
            return {"action": "ACTION_CANCELLED", "reply": t["expired" if expired else "cancelled"]}

        if d.action == "ASK_CLARIFICATION":
            state["clarify_count"] = int(state.get("clarify_count", 0)) + 1
            state["pending"] = {"kind": "clarify", "options": d.options, "expires_at": time.time() + CONFIRMATION_TTL_SECONDS}
            opts = [{"n": i + 1, "label": self.kb.by_id[a].title[lang], "article_id": a} for i, a in enumerate(d.options)]
            listing = "\n".join(f"{o['n']}. {o['label']}" for o in opts)
            return {"action": "ASK_CLARIFICATION", "options": opts, "reply": f"{t['clarify']}\n{listing}\n{t['clarify_end']}"}

        return {"action": "OUT_OF_SCOPE", "reply": t["oos"]}

    def _ask_confirmation(self, card: dict, state: dict, lang: str, article_id: str | None, intro: str | None) -> dict:
        label = card_label(card, lang)
        state["pending"] = {"kind": "confirm_block", "card_id": card["card_id"], "card_label": label,
                            "article_id": article_id, "expires_at": time.time() + CONFIRMATION_TTL_SECONDS}
        msg = T[lang]["confirm_block"].format(card=label)
        return {"action": "CONFIRM_ACTION", "article_id": article_id, "reply": f"{intro}\n\n{msg}" if intro else msg,
                "options": [{"n": 1, "label": "oui" if lang == "fr" else "yes"}, {"n": 2, "label": "non" if lang == "fr" else "no"}]}
