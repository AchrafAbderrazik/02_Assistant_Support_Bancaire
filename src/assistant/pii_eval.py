"""Jeu de test SYNTHÉTIQUE pour le masquage (généré avec une graine fixe) et calcul précision / rappel.

Les numéros générés sont aléatoires (cartes valides au sens de Luhn, IBAN valides au sens du modulo 97) :
ils ne correspondent à aucune personne. Le jeu contient aussi des pièges (montants, dates, références,
numéros de 16 chiffres invalides, « mon PIN est bloqué ») qui ne doivent PAS être masqués.
"""
from __future__ import annotations

import random
import string

from .pii import find_entities

TYPES = ("CARD", "IBAN", "RIB", "PHONE", "EMAIL", "CIN", "SECRET")


def _luhn_complete(prefix: str, length: int, rng: random.Random) -> str:
    body = prefix + "".join(rng.choice(string.digits) for _ in range(length - len(prefix) - 1))
    for d in string.digits:
        cand = body + d
        total = 0
        for i, ch in enumerate(reversed(cand)):
            x = int(ch)
            if i % 2 == 1:
                x = x * 2 - 9 if x * 2 > 9 else x * 2
            total += x
        if total % 10 == 0:
            return cand
    raise RuntimeError


def _non_luhn(length: int, rng: random.Random) -> str:
    while True:
        s = "".join(rng.choice(string.digits) for _ in range(length))
        if s[0] != "0" and not _is_luhn(s):
            return s


def _is_luhn(s: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(s)):
        x = int(ch)
        if i % 2 == 1:
            x = x * 2 - 9 if x * 2 > 9 else x * 2
        total += x
    return total % 10 == 0


def _iban(country: str, bban_len: int, rng: random.Random) -> str:
    bban = "".join(rng.choice(string.digits) for _ in range(bban_len))
    num = "".join(str(int(c, 36)) for c in bban + country + "00")
    check = 98 - int(num) % 97
    return f"{country}{check:02d}{bban}"


def _group(s: str, size: int = 4) -> str:
    return " ".join(s[i:i + size] for i in range(0, len(s), size))


def _card(rng):
    num = _luhn_complete(rng.choice(["4", "51", "53", "55"]), 16, rng)
    style = rng.choice(["space", "dash", "plain"])
    return {"space": _group(num), "dash": "-".join(num[i:i + 4] for i in range(0, 16, 4)), "plain": num}[style]


def _phone(rng):
    d = "".join(rng.choice(string.digits) for _ in range(8))
    lead = rng.choice("567")
    return rng.choice([
        f"+212 {lead} {d[:2]} {d[2:4]} {d[4:6]} {d[6:]}", f"0{lead}{d}", f"0{lead}.{d[:2]}.{d[2:4]}.{d[4:6]}.{d[6:]}",
        f"00212{lead}{d}", f"+33 6 {d[:2]} {d[2:4]} {d[4:6]} {d[6:]}",
    ])


def _email(rng):
    user = "".join(rng.choice(string.ascii_lowercase) for _ in range(rng.randint(4, 9)))
    return f"{user}{rng.choice(['', '.demo', '_test', '2026'])}@{rng.choice(['example.com', 'exemple.ma', 'mail.test'])}"


TEMPLATES = [
    ("fr", "Ma carte {CARD} a été refusée hier", "CARD"),
    ("en", "My card number is {CARD}, it was declined", "CARD"),
    ("fr", "Voici mon IBAN {IBAN} pour le virement", "IBAN"),
    ("en", "Please send it to IBAN {IBAN} thanks", "IBAN"),
    ("fr", "Mon RIB est {RIB} merci de vérifier", "RIB"),
    ("fr", "Rappelez-moi au {PHONE} s'il vous plaît", "PHONE"),
    ("en", "You can call me on {PHONE}", "PHONE"),
    ("fr", "Mon adresse e-mail est {EMAIL}", "EMAIL"),
    ("en", "Send the statement to {EMAIL} please", "EMAIL"),
    ("fr", "Ma CIN : {CIN} pour la vérification", "CIN"),
    ("fr", "mon code PIN est {PIN} et il ne marche plus", "SECRET"),
    ("en", "the CVV is {CVV}, is that ok?", "SECRET"),
    ("fr", "j'ai reçu le code de confirmation {OTP} par SMS", "SECRET"),
    ("fr", "mot de passe : {PWD} je n'arrive pas à me connecter", "SECRET"),
]
NEGATIVES = [
    "J'ai payé 1 250,00 MAD le 12/10/2026 au supermarché",
    "My transfer of 3,500.75 MAD on 2026-10-12 is still pending",
    "Référence de commande {NONLUHN16}",
    "Order reference {NONLUHN16} has not arrived",
    "Mon code PIN est bloqué depuis ce matin",
    "My password is wrong and my pin is blocked",
    "Le retrait de 400 MAD au distributeur à 14h30 n'est pas sorti",
    "I was charged 2 times 280 MAD on 13/10",
    "Mon virement V1001 vers le bénéficiaire 2 a échoué",
    "Card ending 4321 was charged twice",
    "J'attends ma carte depuis 15 jours, livraison prévue le 18/10",
    "The article A07 says I should contact you",
    "Montant total : 12 345 678 MAD sur 24 mois",
    "Mon dossier numéro 2026-10-15-0042 est en cours",
]


def generate(n_per_template: int = 6, seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    cases = []
    for _ in range(n_per_template):
        for lang, tpl, kind in TEMPLATES:
            values = {
                "CARD": _card(rng), "IBAN": _group(_iban("MA", 24, rng)) if rng.random() < 0.5 else (
                    _iban("FR", 23, rng) if rng.random() < 0.5 else _group(_iban("ES", 20, rng))),
                "RIB": _group("".join(rng.choice(string.digits) for _ in range(24)), rng.choice([3, 4, 24])),
                "PHONE": _phone(rng), "EMAIL": _email(rng),
                "CIN": rng.choice(string.ascii_uppercase) + rng.choice(["", rng.choice(string.ascii_uppercase)]) + str(rng.randint(10000, 999999)),
                "PIN": f"{rng.randint(0, 9999):04d}", "CVV": f"{rng.randint(100, 999)}", "OTP": f"{rng.randint(0, 999999):06d}",
                "PWD": rng.choice(["Soleil", "Atlas", "Maison", "Demo"]) + str(rng.randint(10, 9999)) + rng.choice(["!", "#", ""]),
            }
            slot = tpl[tpl.index("{") + 1: tpl.index("}")]
            value = values[slot]
            start = tpl.index("{")
            text = tpl.replace("{" + slot + "}", value)
            cases.append({"lang": lang, "text": text, "gold": [{"type": kind, "start": start, "end": start + len(value)}]})
    for _ in range(n_per_template):
        for neg in NEGATIVES:
            text = neg.replace("{NONLUHN16}", _non_luhn(16, rng))
            cases.append({"lang": "fr", "text": text, "gold": []})
    return cases


def score(cases: list[dict]) -> dict:
    per = {t: {"tp": 0, "fp": 0, "fn": 0, "exact": 0} for t in TYPES}
    neg_fp = 0
    for c in cases:
        pred = find_entities(c["text"])
        matched_pred = set()
        for g in c["gold"]:
            hit = None
            for j, p in enumerate(pred):
                if j not in matched_pred and p.type == g["type"] and p.start < g["end"] and g["start"] < p.end:
                    hit = j
                    break
            if hit is None:
                per[g["type"]]["fn"] += 1
            else:
                matched_pred.add(hit)
                per[g["type"]]["tp"] += 1
                if pred[hit].start == g["start"] and pred[hit].end == g["end"]:
                    per[g["type"]]["exact"] += 1
        for j, p in enumerate(pred):
            if j not in matched_pred:
                per[p.type]["fp"] += 1
                if not c["gold"]:
                    neg_fp += 1
    out = {}
    tot = {"tp": 0, "fp": 0, "fn": 0, "exact": 0}
    for t, v in per.items():
        for k in tot:
            tot[k] += v[k]
        out[t] = _prf(v)
    out["ALL"] = _prf(tot)
    out["n_cases"] = len(cases)
    out["n_negative_cases"] = sum(1 for c in cases if not c["gold"])
    out["false_positives_on_negative_cases"] = neg_fp
    return out


def _prf(v: dict) -> dict:
    p = v["tp"] / (v["tp"] + v["fp"]) if v["tp"] + v["fp"] else None
    r = v["tp"] / (v["tp"] + v["fn"]) if v["tp"] + v["fn"] else None
    f = 2 * p * r / (p + r) if p and r else None
    return {"precision": p, "recall": r, "f1": f, "exact_span_rate": v["exact"] / v["tp"] if v["tp"] else None, **v}
