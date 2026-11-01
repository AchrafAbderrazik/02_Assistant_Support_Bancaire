"""Configuration centralisée (chemins, paramètres, variables d'environnement)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Date de référence des données bancaires simulées (rend les démonstrations reproductibles).
REFERENCE_DATE = "2026-10-15"
SEED = 42
MAX_MESSAGE_CHARS = 1000
CONFIRMATION_TTL_SECONDS = 300
VALIDATION_FRACTION = 0.10
TARGET_ACCEPTED_ACCURACY = 0.95


@dataclass(frozen=True)
class Settings:
    root: Path
    llm_backend: str = "template"          # "template" (défaut) ou "ollama" (optionnel)
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.2:3b"
    ollama_timeout: float = 20.0

    # --- chemins -------------------------------------------------------------------------
    @property
    def raw_dir(self) -> Path:
        return self.root / "data" / "raw"

    @property
    def kb_path(self) -> Path:
        return self.root / "data" / "kb" / "articles.json"

    @property
    def lexicon_path(self) -> Path:
        return self.root / "data" / "lexicon" / "fr_keywords.json"

    @property
    def eval_dir(self) -> Path:
        return self.root / "data" / "eval"

    @property
    def models_dir(self) -> Path:
        return self.root / "models"

    @property
    def model_path(self) -> Path:
        return self.models_dir / "intent_model.joblib"

    @property
    def runtime_dir(self) -> Path:
        return self.root / "runtime"

    @property
    def bank_db(self) -> Path:
        return self.runtime_dir / "bank_demo.db"

    @property
    def conv_db(self) -> Path:
        return self.runtime_dir / "conversations.db"

    @property
    def reports_dir(self) -> Path:
        return self.root / "reports"

    @property
    def ui_dir(self) -> Path:
        return self.root / "ui"

    def ensure_dirs(self) -> None:
        for d in (self.models_dir, self.runtime_dir, self.reports_dir, self.reports_dir / "figures"):
            d.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(cls, root: Path | str | None = None) -> "Settings":
        base = Path(os.environ.get("ASSISTANT_ROOT", root or PROJECT_ROOT))
        return cls(
            root=base,
            llm_backend=os.environ.get("ASSISTANT_LLM", "template").strip().lower(),
            ollama_url=os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434"),
            ollama_model=os.environ.get("OLLAMA_MODEL", "llama3.2:3b"),
            ollama_timeout=float(os.environ.get("OLLAMA_TIMEOUT", "20")),
        )
