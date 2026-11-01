"""Détection et masquage des données personnelles et des secrets dans les messages.

Le texte brut n'est jamais stocké : tout le pipeline (classification, journalisation) travaille sur le texte masqué.

Entités couvertes : numéro de carte (validé par l'algorithme de Luhn), IBAN (validé par le contrôle modulo 97),
RIB marocain (24 chiffres, sans contrôle de la clé), téléphone (formats marocains et internationaux), e-mail,
numéro de CIN (seulement s'il est précédé d'un mot-clé) et secrets (code PIN, CVV, code à usage unique,
mot de passe) qui déclenchent aussi un avertissement de sécurité.
Limites connues : les noms de personnes et les adresses postales ne sont pas détectés (il faudrait un modèle NER).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

LABELS = {
    "CARD": {"fr": "CARTE", "en": "CARD"},
    "IBAN": {"fr": "IBAN", "en": "IBAN"},
    "RIB": {"fr": "RIB", "en": "RIB"},
    "PHONE": {"fr": "TÉLÉPHONE", "en": "PHONE"},
    "EMAIL": {"fr": "E-MAIL", "en": "EMAIL"},
    "CIN": {"fr": "CIN", "en": "NATIONAL_ID"},
    "SECRET": {"fr": "SECRET", "en": "SECRET"},
}


@dataclass(frozen=True)
class Entity:
    type: str
    start: int
    end: int
    last4: str | None = None


@dataclass
class MaskResult:
    text: str
    entities: list[Entity] = field(default_factory=list)

    @property
    def types(self) -> list[str]:
        return sorted({e.type for e in self.entities})

    @property
    def has_secret(self) -> bool:
        return any(e.type == "SECRET" for e in self.entities)

    def summary(self) -> dict:
        counts: dict[str, int] = {}
        for e in self.entities:
            counts[e.type] = counts.get(e.type, 0) + 1
        return counts


# --- validations -------------------------------------------------------------------------
def luhn_ok(digits: str) -> bool:
    if not digits.isdigit() or not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def iban_ok(raw: str) -> bool:
    s = re.sub(r"\s+", "", raw).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", s):
        return False
    moved = s[4:] + s[:4]
    num = "".join(str(int(c, 36)) for c in moved)
    return int(num) % 97 == 1


# --- motifs ------------------------------------------------------------------------------
_SECRET_NUM = re.compile(
    r"(?i)\b(?:code\s+pin|pin(?:\s+code)?|cvv2?|cvc|cryptogramme(?:\s+visuel)?|otp|"
    r"code\s+(?:de\s+)?(?:confirmation|s[ée]curit[ée]|validation|v[ée]rification|re[çc]u\s+par\s+sms)|"
    r"(?:verification|security|one[-\s]time)\s+code)"
    r"(?:\s+(?:est|is|was|:|=|c['’]est))?\s*[:=]?\s*(?P<v>\d{3,8})\b"
)
_SECRET_PWD = re.compile(
    r"(?i)\b(?:mot\s+de\s+passe|password|passcode|mdp)\s*(?:est|is|:|=)\s*[:=]?\s*"
    r"(?P<v>(?=\S*[\d!@#$%^&*_\-])\S{4,64})"
)
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]){10,30}")
_RIB = re.compile(r"(?<!\d)(?:\d[ ]?){23}\d(?!\d)")
_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
_PHONE = re.compile(
    r"(?<![\w+])(?:(?:\+|00)212[\s.-]?|0)[5-7](?:[\s.-]?\d){8}(?!\d)"
    r"|(?<![\w+])\+(?!212)\d{1,3}(?:[\s.-]?\d){7,12}(?!\d)"
)
_EMAIL = re.compile(r"(?i)\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b")
_CIN = re.compile(
    r"(?i)\b(?:cin|c\.i\.n\.?|carte\s+nationale(?:\s+d['’]identit[ée])?|national\s+id(?:\s+number)?)"
    r"\s*(?:n°|no\.?|num(?:[ée]ro)?|number|:)?\s*:?\s*(?P<v>[A-Z]{1,2}\s?\d{4,7})\b"
)


def _overlaps(a: tuple[int, int], spans: list[tuple[int, int]]) -> bool:
    return any(a[0] < e and s < a[1] for s, e in spans)


def _best_card(text: str, start: int, end: int) -> tuple[int, int, str] | None:
    """Plus longue suite de GROUPES de chiffres (séparés par espace ou tiret) de 13 à 19 chiffres valide (Luhn).

    On ne teste que des frontières de groupes : une référence de 16 chiffres collés invalide n'est jamais
    découpée en sous-suites au hasard (sinon environ une chance sur dix de faux positif par découpage).
    """
    groups = [(m.start() + start, m.end() + start) for m in re.finditer(r"\d+", text[start:end])]
    best = None
    for i in range(len(groups)):
        for j in range(len(groups) - 1, i - 1, -1):
            digits = "".join(text[a:b] for a, b in groups[i : j + 1])
            if 13 <= len(digits) <= 19 and luhn_ok(digits):
                cand = (groups[i][0], groups[j][1], digits)
                if best is None or len(digits) > len(best[2]):
                    best = cand
                break
    return best


def _best_iban(text: str, start: int, end: int) -> tuple[int, int] | None:
    """Raccourcit la correspondance par la droite jusqu'à obtenir un IBAN valide (mot collé à la fin)."""
    for stop in range(end, start + 14, -1):
        if text[stop - 1] != " " and iban_ok(text[start:stop]):
            return start, stop
    return None


def find_entities(text: str) -> list[Entity]:
    found: list[Entity] = []
    spans: list[tuple[int, int]] = []

    def add(kind: str, start: int, end: int, last4: str | None = None) -> None:
        if not _overlaps((start, end), spans):
            found.append(Entity(kind, start, end, last4))
            spans.append((start, end))

    for rx in (_SECRET_NUM, _SECRET_PWD):
        for m in rx.finditer(text):
            add("SECRET", m.start("v"), m.end("v"))
    for m in _EMAIL.finditer(text):
        add("EMAIL", m.start(), m.end())
    for m in _IBAN.finditer(text):
        best = _best_iban(text, m.start(), m.end())
        if best:
            add("IBAN", *best)
    for m in _RIB.finditer(text):
        add("RIB", m.start(), m.end())
    for m in _PHONE.finditer(text):
        add("PHONE", m.start(), m.end())
    for m in _CARD.finditer(text):
        best = _best_card(text, m.start(), m.end())
        if best:
            add("CARD", best[0], best[1], best[2][-4:])
    for m in _CIN.finditer(text):
        add("CIN", m.start("v"), m.end("v"))
    return sorted(found, key=lambda e: e.start)


def mask(text: str, lang: str = "fr") -> MaskResult:
    entities = find_entities(text)
    out, pos = [], 0
    for e in entities:
        out.append(text[pos : e.start])
        label = LABELS[e.type]["fr" if lang == "fr" else "en"]
        out.append(f"[{label} ****{e.last4}]" if e.type == "CARD" and e.last4 else f"[{label}]")
        pos = e.end
    out.append(text[pos:])
    return MaskResult("".join(out), entities)
