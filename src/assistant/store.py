"""Journal des conversations (SQLite). Seul le texte MASQUÉ est enregistré, jamais le message brut."""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

DDL = """
CREATE TABLE IF NOT EXISTS conversations (
    conversation_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, created_at TEXT NOT NULL, state_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id),
    at_utc TEXT NOT NULL, role TEXT NOT NULL CHECK (role IN ('user','assistant')), text_masked TEXT NOT NULL,
    lang TEXT, action TEXT, article_id TEXT, intent TEXT, confidence REAL, latency_ms REAL, pii_types TEXT
);
CREATE TABLE IF NOT EXISTS cases (
    case_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id),
    customer_id TEXT NOT NULL, at_utc TEXT NOT NULL, reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'ouvert'
);
CREATE INDEX IF NOT EXISTS ix_msg_conv ON messages(conversation_id, id);
"""


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ConversationStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._con()) as con:
            con.executescript(DDL)

    def _con(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con

    def get_or_create(self, conversation_id: str | None, customer_id: str) -> tuple[str, dict]:
        with closing(self._con()) as con:
            if conversation_id:
                row = con.execute("SELECT customer_id, state_json FROM conversations WHERE conversation_id = ?",
                                  (conversation_id,)).fetchone()
                if row is not None:
                    if row["customer_id"] != customer_id:
                        raise PermissionError("conversation d'un autre client")
                    return conversation_id, json.loads(row["state_json"])
            cid = uuid.uuid4().hex
            con.execute("INSERT INTO conversations VALUES (?,?,?,?)", (cid, customer_id, now_utc(), "{}"))
            con.commit()
            return cid, {}

    def save_state(self, conversation_id: str, state: dict) -> None:
        with closing(self._con()) as con:
            con.execute("UPDATE conversations SET state_json = ? WHERE conversation_id = ?",
                        (json.dumps(state, ensure_ascii=False), conversation_id))
            con.commit()

    def log(self, conversation_id: str, role: str, text_masked: str, **meta) -> None:
        with closing(self._con()) as con:
            con.execute(
                "INSERT INTO messages (conversation_id, at_utc, role, text_masked, lang, action, article_id, intent, "
                "confidence, latency_ms, pii_types) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (conversation_id, now_utc(), role, text_masked, meta.get("lang"), meta.get("action"), meta.get("article_id"),
                 meta.get("intent"), meta.get("confidence"), meta.get("latency_ms"), ",".join(meta.get("pii_types") or [])))
            con.commit()

    def open_case(self, conversation_id: str, customer_id: str, reason: str) -> str:
        case_id = "D-" + uuid.uuid4().hex[:8].upper()
        with closing(self._con()) as con:
            con.execute("INSERT INTO cases (case_id, conversation_id, customer_id, at_utc, reason) VALUES (?,?,?,?,?)",
                        (case_id, conversation_id, customer_id, now_utc(), reason))
            con.commit()
        return case_id

    def transcript(self, conversation_id: str) -> list[dict]:
        with closing(self._con()) as con:
            return [dict(r) for r in con.execute(
                "SELECT at_utc, role, text_masked, lang, action, article_id, intent, confidence, latency_ms, pii_types "
                "FROM messages WHERE conversation_id = ? ORDER BY id", (conversation_id,))]

    def cases(self, limit: int = 50) -> list[dict]:
        with closing(self._con()) as con:
            return [dict(r) for r in con.execute("SELECT * FROM cases ORDER BY at_utc DESC LIMIT ?", (limit,))]

    def stats(self) -> dict:
        with closing(self._con()) as con:
            by_action = {r[0]: r[1] for r in con.execute(
                "SELECT action, COUNT(*) FROM messages WHERE role = 'assistant' GROUP BY action")}
            n_conv = con.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        return {"conversations": n_conv, "replies_by_action": by_action}
