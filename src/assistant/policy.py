"""Politique de décision : quand répondre, appeler un outil, demander confirmation, clarifier ou escalader.

Règles déterministes, lisibles et testées (pas de « boîte noire ») :
1. une confirmation, un choix de carte ou une clarification en attente est traité en priorité ;
2. une demande explicite de conseiller -> escalade ;
3. compréhension fiable (seuil appris sur la validation) -> réponse documentée, outil en lecture,
   ou parcours de blocage avec confirmation ; les contestations sont toujours transmises à un conseiller ;
4. compréhension incertaine mais sujet bancaire -> question de clarification (une fois), puis escalade ;
5. hors périmètre -> refus poli avec proposition de conseiller.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .text import normalize

ACTIONS = (
    "GREETING", "ANSWER_FROM_KB", "CALL_TOOL", "CHOOSE_CARD", "CONFIRM_ACTION", "ACTION_DONE", "ACTION_CANCELLED",
    "ASK_CLARIFICATION", "ESCALATE_HUMAN", "OUT_OF_SCOPE",
)

HUMAN_RE = re.compile(
    r"\b(conseiller|conseillere|humain|agent|operateur|vraie personne)\b|"
    r"\b(human|advisor|adviser|real person|someone real|live agent|representative)\b"
)
GREETING_RE = re.compile(r"^(bonjour|bonsoir|salut|salam|hello|hi|hey|good (morning|afternoon|evening))( \w+)?$")
YES_RE = re.compile(r"^(oui|ouais|ok|d accord|je confirme|confirme|confirmer|vas y|yes|yep|yeah|sure|confirm|i confirm|go ahead)\b")
NO_RE = re.compile(r"^(non|annule|annuler|stop|pas maintenant|no|nope|cancel|don t|do not)\b")
CHOICE_RE = re.compile(r"^(?:le |la |option |choix |number |n )?([1-9])\b")


@dataclass
class NLU:
    lang: str
    ranking: list[tuple[str, float]]
    confidence: float
    accepted: bool
    in_domain: bool
    method: str
    intent: str | None = None


@dataclass
class Decision:
    action: str
    article_id: str | None = None
    reason: str = ""
    options: list = field(default_factory=list)
    choice: int | None = None


def wants_human(message: str) -> bool:
    return bool(HUMAN_RE.search(normalize(message)))


def is_greeting(message: str) -> bool:
    return bool(GREETING_RE.match(normalize(message)))


def parse_choice(message: str, n_options: int) -> int | None:
    m = CHOICE_RE.match(normalize(message))
    if m and 1 <= int(m.group(1)) <= n_options:
        return int(m.group(1)) - 1
    return None


def decide_pending(message: str, pending: dict) -> Decision | None:
    """Réponse à une étape en attente (confirmation, choix de carte, clarification). None = message ordinaire."""
    norm = normalize(message)
    kind = pending.get("kind")
    if kind == "confirm_block":
        if YES_RE.match(norm):
            return Decision("ACTION_DONE", reason="confirmation explicite")
        if NO_RE.match(norm):
            return Decision("ACTION_CANCELLED", reason="refus explicite")
        return None
    if kind == "choose_card":
        idx = parse_choice(message, len(pending.get("options", [])))
        if idx is not None:
            return Decision("CONFIRM_ACTION", reason="carte choisie", choice=idx)
        if NO_RE.match(norm):
            return Decision("ACTION_CANCELLED", reason="refus explicite")
        return None
    if kind == "clarify":
        idx = parse_choice(message, len(pending.get("options", [])))
        if idx is not None:
            return Decision("ANSWER_FROM_KB", article_id=pending["options"][idx], reason="choix de clarification", choice=idx)
        return None
    return None


def decide(nlu: NLU, article_lookup, clarify_count: int) -> Decision:
    if nlu.accepted:
        art = article_lookup(nlu.ranking[0][0])
        if art.tool == "block_card":
            return Decision("CHOOSE_CARD", art.id, reason="blocage demandé : confirmation obligatoire")
        if art.sensitive and art.tool:
            return Decision("ESCALATE_HUMAN", art.id, reason="opération contestée : examen par un conseiller")
        if art.tool:
            return Decision("CALL_TOOL", art.id, reason=f"outil en lecture : {art.tool}")
        return Decision("ANSWER_FROM_KB", art.id, reason="réponse documentée")
    if nlu.in_domain:
        if clarify_count >= 1:
            return Decision("ESCALATE_HUMAN", reason="incertitude persistante après clarification")
        return Decision("ASK_CLARIFICATION", options=[a for a, _ in nlu.ranking[:3]], reason="confiance insuffisante")
    return Decision("OUT_OF_SCOPE", reason="aucun terme du périmètre couvert")
