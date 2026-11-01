"""Outils de texte : normalisation, découpage, racinisation légère et détection de langue FR/EN."""
from __future__ import annotations

import re
import unicodedata

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_SENT_RE = re.compile(r"(?<=[.!?])\s+")

FR_STOP = set(
    """a ai au aux avec ce ces cet cette d de des du elle en est et il ils j je l la le les leur lui m ma mais me
    mes moi mon n ne nos notre nous on ou par pas pour qu que qui s sa se ses si son sont sur ta te tes toi ton
    tu un une vos votre vous y ete etre avoir fait faire comment quoi quand pourquoi est-ce ca cela ceci tout
    tous toute toutes tres plus bien encore deja aussi alors donc car puis comme dans sans sous chez via""".split()
)
EN_STOP = set(
    """a an and are as at be been but by can could did do does for from had has have how i if in into is it its
    me my of on or our so than that the their them then there these this those to too us was we were what when
    where which who why will with would you your yours am im ive id dont didnt cant isnt wasnt just still please
    get got any some""".split()
)

# Marqueurs utilisés pour la détection de langue (mots fréquents, sans accents après normalisation).
FR_MARKERS = set(
    """je j ai mon ma mes est pas une un le la les des du pour avec que qui vous votre nous c n l d qu
    carte compte virement retrait paiement frais recu toujours encore depuis bloquee bloque perdu volee
    argent bonjour merci pourquoi comment quand ou rembourse rembourser commande payer pu peux""".split()
)
EN_MARKERS = set(
    """i my the is not a an it was have has how what why when can do does did you your of to for with
    card account transfer payment money still yet hello hi thanks please been got cant dont didnt im""".split()
)


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def normalize(text: str) -> str:
    """Minuscules, sans accents, apostrophes et ponctuation remplacées par des espaces."""
    t = strip_accents(text.lower())
    t = t.replace("’", " ").replace("'", " ")
    return " ".join(_TOKEN_RE.findall(t))


def tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(normalize(text))


def _stem_fr(tok: str) -> str:
    for suf in ("ements", "ement", "ations", "ation", "ees", "ee", "es", "er", "ez", "e", "s", "x"):
        if tok.endswith(suf) and len(tok) - len(suf) >= 4:
            return tok[: -len(suf)]
    return tok


def _stem_en(tok: str) -> str:
    for suf in ("ings", "ing", "ied", "ies", "ed", "es", "s"):
        if tok.endswith(suf) and len(tok) - len(suf) >= 4:
            return tok[: -len(suf)]
    return tok


def content_tokens(text: str, lang: str) -> list[str]:
    """Jetons utiles pour la recherche : sans mots vides, racinisation légère selon la langue."""
    stop, stem = (FR_STOP, _stem_fr) if lang == "fr" else (EN_STOP, _stem_en)
    return [stem(t) for t in tokens(text) if t not in stop and (len(t) > 1 or t.isdigit())]


def detect_language(text: str, default: str = "fr") -> str:
    """Détection FR/EN par marqueurs lexicaux et accents (rapide, sans dépendance)."""
    raw = text.lower()
    toks = tokens(text)
    fr = sum(t in FR_MARKERS for t in toks) + 2 * len(re.findall(r"[éèêàùçôîâ]", raw))
    fr += 2 * len(re.findall(r"\b(?:j|n|l|d|qu|c)['’]", raw))
    en = sum(t in EN_MARKERS for t in toks)
    if fr == en:
        return default
    return "fr" if fr > en else "en"


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_RE.split(text) if s.strip()]


# Termes du périmètre couvert (cartes, paiements, virements, recharges, identité, compte).
# Sert de garde-fou « hors périmètre » : sans aucun de ces termes, l'assistant ne répond pas au hasard.
_DOMAIN_EXACT = {
    "fr": set("pin gab dab tpe mad vol nom age kyc rib iban otp".split()),
    "en": set("pin atm fee fees old age kyc app top otp".split()),
}
_DOMAIN_PREFIX = {
    "fr": tuple(
        """carte compte virement vire paiement payer paye retrait retir frais commission recharg alimente
        code cheque depot depos versement rembours identit justificatif taux change devise conversion
        distributeur prelevement debit solde banque bancaire beneficiaire operation transaction argent
        adresse expir opposition perdu perte pirat fraude frauduleu apple google visa mastercard virtuel
        achat commer marchand terminal contact application appli clotur fermer pays etranger donnees
        telephone livraison activ passe euro dollar dirham espece billet fonds plafond limite attente
        relev bloqu refus echou annul credit encaiss""".split()
    ),
    "en": tuple(
        """card account transfer payment pay paid withdraw cash charge topup topping cheque check deposit
        refund identity verif exchange rate currenc fiat money balance bank beneficiar transaction debit
        statement address detail expir lost stolen stole apple google visa mastercard virtual disposable
        merchant contactless close terminat country phone deliver arriv activat password passcode euro
        dollar pound salary fund limit declin pending spare physical swallow machine wallet cancel revert
        fail reject block frozen pending receiv sent send""".split()
    ),
}


def has_domain_term(text: str, lang: str) -> bool:
    toks = tokens(text)
    if any(t in _DOMAIN_EXACT[lang] for t in toks):
        return True
    return any(t.startswith(_DOMAIN_PREFIX[lang]) for t in toks)
