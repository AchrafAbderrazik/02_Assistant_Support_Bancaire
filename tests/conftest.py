"""Fixtures : un projet temporaire (copie des données) avec un modèle entraîné une seule fois par session."""
import shutil
from pathlib import Path

import pytest

from assistant.bankdb import BankTools, seed_database
from assistant.config import Settings
from assistant.retrieval import KnowledgeBase
from assistant.service import AssistantService
from assistant.store import ConversationStore
from assistant.train import train_all

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def project(tmp_path_factory):
    root = tmp_path_factory.mktemp("projet")
    shutil.copytree(ROOT / "data", root / "data")
    shutil.copytree(ROOT / "ui", root / "ui")
    settings = Settings(root=root)
    settings.ensure_dirs()
    seed_database(settings.bank_db)
    model, _ = train_all(settings, kinds=("svm_calibrated",))  # modèle le plus rapide pour les tests
    kb = KnowledgeBase.load(settings.kb_path, settings.lexicon_path)
    return settings, model, kb


@pytest.fixture
def service(project, tmp_path):
    settings, model, kb = project
    db = tmp_path / "bank.db"
    seed_database(db)
    return AssistantService(settings, model=model, kb=kb, tools=BankTools(db), store=ConversationStore(tmp_path / "conv.db"))
