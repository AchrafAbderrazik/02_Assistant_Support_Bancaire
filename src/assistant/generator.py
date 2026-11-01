"""Rédaction des réponses.

Par défaut, la réponse est EXTRACTIVE : phrases de l'article retenu + résultats d'outils mis en forme + source citée.
Aucun contenu n'est inventé. Un reformulateur LLM local (Ollama) est disponible en option : il ne reçoit que le
texte masqué et le contexte, et sa sortie est rejetée (retour au gabarit) si elle contient un nombre absent du
contexte ou si le serveur ne répond pas. Ce mode n'est pas activé ni évalué dans les mesures du projet.
"""
from __future__ import annotations

import json
import re
import urllib.request
from datetime import date

T = {
    "fr": {
        "source": "Source : article {id} « {title} » (base de connaissances de la Banque Démo, fictive).",
        "cards": "Vos cartes : {items}.",
        "card_item": "{network} ****{last4} ({kind}) — {status}{extra}",
        "delivery": ", livraison prévue le {d}",
        "expiry": ", expire fin {d}",
        "tx": "Vos dernières opérations : {items}.",
        "tx_item": "{d} {label} {amount} ({status})",
        "dup": "Attention : opérations identiques détectées — {items}.",
        "dup_item": "{n} × {label} {amount} le {d}",
        "tr": "Vos derniers virements : {items}.",
        "tr_item": "{d} vers {benef}, {amount} — {status}{extra}",
        "tr_expected": ", arrivée prévue le {d}",
        "secret": "Pour votre sécurité, ne communiquez jamais votre code PIN, cryptogramme, mot de passe ou code reçu par SMS : je l'ai masqué et il n'a pas été enregistré. S'il a pu être divulgué, changez-le ou bloquez votre carte.",
        "pii": "J'ai masqué les données personnelles de votre message ({types}) : elles ne sont pas enregistrées et ne sont pas nécessaires ici.",
        "clarify": "Je veux être sûr de bien comprendre. Votre question concerne-t-elle :",
        "clarify_end": "Répondez par le numéro correspondant, ou reformulez.",
        "oos": "Je ne peux répondre qu'aux questions sur les cartes, paiements, retraits, virements, recharges, l'identité et le compte. Pour toute autre demande, je peux vous mettre en relation avec un conseiller.",
        "escalate": "Je transmets votre demande à un conseiller (dossier {case}). Il disposera de l'historique masqué de cette conversation.",
        "escalate_dispute": "Pour une opération contestée, un conseiller doit examiner votre dossier : je l'ai transmis (dossier {case}).",
        "choose_card": "Quelle carte souhaitez-vous bloquer ?",
        "confirm_block": "Je peux bloquer immédiatement la carte {card}. Ce blocage est définitif : une nouvelle carte devra être commandée. Confirmez-vous ? (oui / non)",
        "blocked": "C'est fait : la carte {card} est bloquée. Aucune nouvelle opération ne sera acceptée avec cette carte. Vous pouvez commander une carte de remplacement depuis l'application.",
        "already_blocked": "La carte {card} était déjà bloquée.",
        "cancelled": "D'accord, je n'ai rien modifié.",
        "no_card": "Je ne trouve aucune carte active à bloquer sur votre compte. Un conseiller peut vous aider.",
        "expired": "La demande de confirmation a expiré. Reformulez votre demande si nécessaire.",
        "greeting": "Bonjour ! Je suis l'assistant de démonstration de la Banque Démo (fictive). Posez votre question sur votre carte, vos paiements, vos virements ou votre compte.",
        "status": {"active": "active", "bloquée": "bloquée", "en_livraison": "en livraison", "expirée": "expirée",
                   "effectuée": "effectuée", "en_attente": "en attente", "annulée": "annulée",
                   "effectué": "effectué", "échoué": "échoué", "annulé": "annulé"},
        "kind": {"physique": "physique", "virtuelle": "virtuelle"},
    },
    "en": {
        "source": "Source: article {id} \"{title}\" (Demo Bank knowledge base, fictional).",
        "cards": "Your cards: {items}.",
        "card_item": "{network} ****{last4} ({kind}) — {status}{extra}",
        "delivery": ", expected delivery {d}",
        "expiry": ", expires end of {d}",
        "tx": "Your latest transactions: {items}.",
        "tx_item": "{d} {label} {amount} ({status})",
        "dup": "Warning: identical transactions detected — {items}.",
        "dup_item": "{n} × {label} {amount} on {d}",
        "tr": "Your latest transfers: {items}.",
        "tr_item": "{d} to {benef}, {amount} — {status}{extra}",
        "tr_expected": ", expected on {d}",
        "secret": "For your security, never share your PIN, CVV, password or SMS code: I masked it and it was not stored. If it may have been disclosed, change it or block your card.",
        "pii": "I masked the personal data in your message ({types}): it is not stored and is not needed here.",
        "clarify": "I want to make sure I understand. Is your question about:",
        "clarify_end": "Reply with the matching number, or rephrase.",
        "oos": "I can only answer questions about cards, payments, withdrawals, transfers, top-ups, identity and your account. For anything else, I can connect you with an advisor.",
        "escalate": "I'm passing your request to an advisor (case {case}). They will see the masked history of this conversation.",
        "escalate_dispute": "A disputed transaction must be reviewed by an advisor: I've opened a case for you (case {case}).",
        "choose_card": "Which card would you like to block?",
        "confirm_block": "I can block card {card} right away. Blocking is permanent: a new card will have to be ordered. Do you confirm? (yes / no)",
        "blocked": "Done: card {card} is now blocked. No new transactions will be accepted with it. You can order a replacement card in the app.",
        "already_blocked": "Card {card} was already blocked.",
        "cancelled": "OK, I haven't changed anything.",
        "no_card": "I can't find any active card to block on your account. An advisor can help you.",
        "expired": "The confirmation request has expired. Please ask again if needed.",
        "greeting": "Hello! I'm the demo assistant of Demo Bank (fictional). Ask me about your card, payments, transfers or account.",
        "status": {"active": "active", "bloquée": "blocked", "en_livraison": "in delivery", "expirée": "expired",
                   "effectuée": "completed", "en_attente": "pending", "annulée": "reverted",
                   "effectué": "completed", "échoué": "failed", "annulé": "cancelled"},
        "kind": {"physique": "physical", "virtuelle": "virtual"},
    },
}

PII_NAMES = {
    "fr": {"CARD": "carte", "IBAN": "IBAN", "RIB": "RIB", "PHONE": "téléphone", "EMAIL": "e-mail", "CIN": "CIN"},
    "en": {"CARD": "card", "IBAN": "IBAN", "RIB": "RIB", "PHONE": "phone", "EMAIL": "email", "CIN": "national ID"},
}


def fmt_amount(x: float, lang: str) -> str:
    sign = "−" if x < 0 else ""
    s = f"{abs(x):,.2f}"
    if lang == "fr":
        s = s.replace(",", " ").replace(".", ",")
        return f"{sign}{s} MAD"
    return f"{sign}{s} MAD"


def fmt_date(iso: str | None, lang: str) -> str:
    if not iso:
        return ""
    if len(iso) == 7:  # AAAA-MM
        y, m = iso.split("-")
        return f"{m}/{y}"
    d = date.fromisoformat(iso)
    return d.strftime("%d/%m/%Y") if lang == "fr" else d.isoformat()


def card_label(card: dict, lang: str) -> str:
    status = "" if card["status"] == "active" else ", " + T[lang]["status"][card["status"]]
    return f"{card['network']} ****{card['last4']} ({T[lang]['kind'][card['kind']]}{status})"


def format_tool(result: dict | None, lang: str) -> list[str]:
    if not result:
        return []
    t, out = T[lang], []
    if result["tool"] == "get_card_status":
        items = []
        for c in result["cards"]:
            extra = t["delivery"].format(d=fmt_date(c["expected_delivery"], lang)) if c["status"] == "en_livraison" else ""
            if c["status"] == "active":
                extra = t["expiry"].format(d=fmt_date(c["expiry"], lang))
            items.append(t["card_item"].format(network=c["network"], last4=c["last4"], kind=t["kind"][c["kind"]],
                                               status=t["status"][c["status"]], extra=extra))
        out.append(t["cards"].format(items=" ; ".join(items) if lang == "fr" else "; ".join(items)))
    elif result["tool"] == "list_recent_transactions":
        items = [t["tx_item"].format(d=fmt_date(x["tx_date"], lang), label=x["label"], amount=fmt_amount(x["amount_mad"], lang),
                                     status=t["status"][x["status"]]) for x in result["transactions"]]
        out.append(t["tx"].format(items=" ; ".join(items) if lang == "fr" else "; ".join(items)))
        if result.get("possible_duplicates"):
            dups = [t["dup_item"].format(n=x["n"], label=x["label"], amount=fmt_amount(x["amount_mad"], lang),
                                         d=fmt_date(x["tx_date"], lang)) for x in result["possible_duplicates"]]
            out.append(t["dup"].format(items=" ; ".join(dups)))
    elif result["tool"] == "get_transfer_status":
        items = []
        for x in result["transfers"]:
            extra = t["tr_expected"].format(d=fmt_date(x["expected_on"], lang)) if x["status"] == "en_attente" and x["expected_on"] else ""
            items.append(t["tr_item"].format(d=fmt_date(x["created_on"], lang), benef=x["beneficiary"],
                                             amount=fmt_amount(x["amount_mad"], lang), status=t["status"][x["status"]], extra=extra))
        out.append(t["tr"].format(items=" ; ".join(items) if lang == "fr" else "; ".join(items)))
    return out


def notices(lang: str, pii_types: list[str], has_secret: bool) -> list[str]:
    out = []
    if has_secret:
        out.append(T[lang]["secret"])
    other = [PII_NAMES[lang][p] for p in pii_types if p != "SECRET"]
    if other:
        out.append(T[lang]["pii"].format(types=", ".join(other)))
    return out


def compose_answer(lang: str, article, sentences: list[str], tool_lines: list[str]) -> str:
    parts = [" ".join(sentences)] + tool_lines
    parts.append(T[lang]["source"].format(id=article.id, title=article.title[lang]))
    return "\n\n".join(p for p in parts if p)


# --- reformulation optionnelle par un LLM local ---------------------------------------------
_NUM = re.compile(r"\d+(?:[.,]\d+)?")


def numbers_supported(output: str, context: str) -> bool:
    """Garde-fou anti-hallucination : tout nombre de la sortie doit figurer dans le contexte fourni."""
    ctx = {n.replace(",", ".") for n in _NUM.findall(context.replace(" ", "").replace(" ", ""))}
    out = {n.replace(",", ".") for n in _NUM.findall(output.replace(" ", "").replace(" ", ""))}
    return out <= ctx


class OllamaRewriter:
    def __init__(self, url: str, model: str, timeout: float = 20.0):
        self.url, self.model, self.timeout = url.rstrip("/"), model, timeout

    def _call(self, prompt: str) -> str:
        body = json.dumps({"model": self.model, "prompt": prompt, "stream": False, "options": {"temperature": 0}}).encode()
        req = urllib.request.Request(f"{self.url}/api/generate", data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310 (URL locale configurée)
            return json.loads(resp.read().decode("utf-8")).get("response", "").strip()

    def rewrite(self, lang: str, question_masked: str, draft: str) -> str | None:
        language = "français" if lang == "fr" else "English"
        prompt = (
            f"Tu es l'assistant d'une banque fictive. Réécris la RÉPONSE ci-dessous en {language}, de façon claire et "
            "polie, en 120 mots maximum. N'ajoute AUCUNE information, aucun chiffre, aucun délai ni montant absent de "
            "la RÉPONSE. Conserve la ligne « Source ».\n\n"
            f"QUESTION (données personnelles masquées) : {question_masked}\n\nRÉPONSE :\n{draft}\n"
        )
        try:
            out = self._call(prompt)
        except Exception:  # serveur absent, délai dépassé, réponse invalide : retour au gabarit
            return None
        if not out or len(out) > 1500 or not numbers_supported(out, draft):
            return None
        return out
