"""Base bancaire SIMULÉE (SQLite) et outils appelés par l'assistant.

Toutes les données sont générées de façon déterministe (graine fixe) : clients, cartes, opérations et virements
sont fictifs. Les outils reçoivent l'identifiant client du contexte de session (client « connecté »),
jamais du texte du message, et vérifient que la ressource appartient bien à ce client.
"""
from __future__ import annotations

import random
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .config import REFERENCE_DATE, SEED

DDL = """
PRAGMA foreign_keys = ON;
CREATE TABLE customers (customer_id TEXT PRIMARY KEY, display_name TEXT NOT NULL, segment TEXT NOT NULL);
CREATE TABLE cards (
    card_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customers(customer_id),
    kind TEXT NOT NULL CHECK (kind IN ('physique','virtuelle')), network TEXT NOT NULL, last4 TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active','bloquée','en_livraison','expirée')),
    expiry TEXT NOT NULL, ordered_on TEXT, expected_delivery TEXT
);
CREATE TABLE transactions (
    tx_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customers(customer_id),
    card_id TEXT REFERENCES cards(card_id), tx_date TEXT NOT NULL, label TEXT NOT NULL,
    category TEXT NOT NULL, amount_mad REAL NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('effectuée','en_attente','annulée'))
);
CREATE TABLE transfers (
    transfer_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customers(customer_id),
    created_on TEXT NOT NULL, beneficiary TEXT NOT NULL, amount_mad REAL NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('en_attente','effectué','échoué','annulé')), expected_on TEXT
);
CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, at_utc TEXT NOT NULL, customer_id TEXT NOT NULL,
    action TEXT NOT NULL, target TEXT NOT NULL, detail TEXT
);
CREATE INDEX ix_tx_customer ON transactions(customer_id, tx_date);
CREATE INDEX ix_tr_customer ON transfers(customer_id, created_on);
"""

MERCHANTS = [
    ("Supermarché (démo)", "courses"), ("Station-service (démo)", "carburant"), ("Pharmacie (démo)", "santé"),
    ("Café (démo)", "restauration"), ("Librairie (démo)", "loisirs"), ("Opérateur télécom (démo)", "abonnement"),
    ("Site marchand en ligne (démo)", "achats en ligne"), ("Retrait distributeur (démo)", "retrait"),
]


def _last4(rng: random.Random) -> str:
    return f"{rng.randint(0, 9999):04d}"


def seed_database(path: Path, seed: int = SEED) -> dict:
    """(Re)crée la base simulée. Retourne le nombre de lignes par table."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    rng = random.Random(seed)
    ref = date.fromisoformat(REFERENCE_DATE)
    customers = [("C001", "Client démo 1", "particulier"), ("C002", "Client démo 2", "particulier"),
                 ("C003", "Client démo 3", "jeune"), ("C004", "Client démo 4", "premium")]
    cards, txs, transfers = [], [], []
    for n, (cid, _, _) in enumerate(customers, start=1):
        main = f"K{n}01"
        cards.append((main, cid, "physique", rng.choice(["Visa", "Mastercard"]), _last4(rng), "active",
                      f"{ref.year + rng.randint(1, 3)}-{rng.randint(1, 12):02d}", None, None))
        if n == 2:  # carte de remplacement en cours de livraison
            cards.append((f"K{n}02", cid, "physique", "Visa", _last4(rng), "en_livraison", f"{ref.year + 4}-06",
                           (ref - timedelta(days=6)).isoformat(), (ref + timedelta(days=3)).isoformat()))
        if n == 3:  # carte bientôt expirée + carte virtuelle
            cards[-1] = (main, cid, "physique", "Mastercard", _last4(rng), "active", f"{ref.year}-11", None, None)
            cards.append((f"K{n}02", cid, "virtuelle", "Mastercard", _last4(rng), "active", f"{ref.year + 2}-03", None, None))
        for t in range(30):
            d = ref - timedelta(days=rng.randint(0, 29))
            label, cat = rng.choice(MERCHANTS)
            amount = round(rng.uniform(20, 900) if cat != "retrait" else rng.choice([200, 400, 500, 1000]), 2)
            status = "en_attente" if d >= ref - timedelta(days=1) and rng.random() < 0.6 else "effectuée"
            txs.append((f"T{n}{t:03d}", cid, main, d.isoformat(), label, cat, -amount, status))
        # cas de démonstration explicites
        txs.append((f"T{n}900", cid, main, (ref - timedelta(days=3)).isoformat(), "Site marchand en ligne (démo)",
                    "achats en ligne", -349.0, "annulée"))
        if n == 2:  # débit en double
            for k in (901, 902):
                txs.append((f"T{n}{k}", cid, main, (ref - timedelta(days=2)).isoformat(), "Restaurant (démo)",
                            "restauration", -280.0, "effectuée"))
        for k, status in enumerate(["effectué", "en_attente", "échoué"] if n in (1, 2) else ["effectué"]):
            created = ref - timedelta(days=[9, 1, 4][k])
            transfers.append((f"V{n}{k:02d}", cid, created.isoformat(), f"Bénéficiaire démo {k + 1}",
                              round(rng.uniform(300, 5000), 2), status,
                              (created + timedelta(days=2)).isoformat() if status != "échoué" else None))
    with closing(sqlite3.connect(path)) as con:
        con.executescript(DDL)
        con.executemany("INSERT INTO customers VALUES (?,?,?)", customers)
        con.executemany("INSERT INTO cards VALUES (?,?,?,?,?,?,?,?,?)", cards)
        con.executemany("INSERT INTO transactions VALUES (?,?,?,?,?,?,?,?)", txs)
        con.executemany("INSERT INTO transfers VALUES (?,?,?,?,?,?,?)", transfers)
        con.commit()
        return {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in ("customers", "cards", "transactions", "transfers")}


class BankTools:
    """Outils exposés à l'assistant. Lecture seule, sauf block_card (après confirmation explicite)."""

    TOOLS = ("get_card_status", "block_card", "list_recent_transactions", "get_transfer_status")

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    def _con(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        return con

    def customers(self) -> list[dict]:
        with closing(self._con()) as con:
            return [dict(r) for r in con.execute("SELECT * FROM customers ORDER BY customer_id")]

    def customer_exists(self, customer_id: str) -> bool:
        with closing(self._con()) as con:
            return con.execute("SELECT 1 FROM customers WHERE customer_id = ?", (customer_id,)).fetchone() is not None

    def get_card_status(self, customer_id: str) -> dict:
        with closing(self._con()) as con:
            rows = con.execute(
                "SELECT card_id, kind, network, last4, status, expiry, expected_delivery FROM cards "
                "WHERE customer_id = ? ORDER BY card_id", (customer_id,)).fetchall()
        return {"tool": "get_card_status", "cards": [dict(r) for r in rows]}

    def list_recent_transactions(self, customer_id: str, limit: int = 5, statuses: tuple[str, ...] | None = None) -> dict:
        limit = max(1, min(int(limit), 20))
        sql = "SELECT tx_id, tx_date, label, amount_mad, status FROM transactions WHERE customer_id = ?"
        params: list = [customer_id]
        if statuses:
            sql += f" AND status IN ({','.join('?' * len(statuses))})"
            params += list(statuses)
        sql += " ORDER BY tx_date DESC, tx_id DESC LIMIT ?"
        params.append(limit)
        with closing(self._con()) as con:
            rows = [dict(r) for r in con.execute(sql, params)]
            dup = con.execute(
                "SELECT label, amount_mad, tx_date, COUNT(*) n FROM transactions WHERE customer_id = ? "
                "AND status = 'effectuée' GROUP BY label, amount_mad, tx_date HAVING n > 1", (customer_id,)).fetchall()
        return {"tool": "list_recent_transactions", "transactions": rows, "possible_duplicates": [dict(r) for r in dup]}

    def get_transfer_status(self, customer_id: str, limit: int = 3) -> dict:
        with closing(self._con()) as con:
            rows = con.execute(
                "SELECT transfer_id, created_on, beneficiary, amount_mad, status, expected_on FROM transfers "
                "WHERE customer_id = ? ORDER BY created_on DESC LIMIT ?", (customer_id, max(1, min(int(limit), 10)))).fetchall()
        return {"tool": "get_transfer_status", "transfers": [dict(r) for r in rows]}

    def blockable_cards(self, customer_id: str) -> list[dict]:
        return [c for c in self.get_card_status(customer_id)["cards"] if c["status"] in ("active", "en_livraison")]

    def block_card(self, customer_id: str, card_id: str, reason: str) -> dict:
        """Bloque une carte du client connecté. Refuse toute carte appartenant à un autre client."""
        with closing(self._con()) as con:
            row = con.execute("SELECT status FROM cards WHERE card_id = ? AND customer_id = ?", (card_id, customer_id)).fetchone()
            if row is None:
                raise PermissionError("carte introuvable pour ce client")
            if row["status"] == "bloquée":
                return {"tool": "block_card", "card_id": card_id, "status": "bloquée", "changed": False}
            con.execute("UPDATE cards SET status = 'bloquée' WHERE card_id = ? AND customer_id = ?", (card_id, customer_id))
            con.execute(
                "INSERT INTO audit_log (at_utc, customer_id, action, target, detail) VALUES (?,?,?,?,?)",
                (datetime.now(timezone.utc).isoformat(timespec="seconds"), customer_id, "block_card", card_id, reason[:100]))
            con.commit()
        return {"tool": "block_card", "card_id": card_id, "status": "bloquée", "changed": True}

    def run(self, tool: str, customer_id: str) -> dict:
        if tool == "get_card_status":
            return self.get_card_status(customer_id)
        if tool == "list_recent_transactions":
            return self.list_recent_transactions(customer_id)
        if tool == "get_transfer_status":
            return self.get_transfer_status(customer_id)
        raise ValueError(f"outil non autorisé sans confirmation : {tool}")
