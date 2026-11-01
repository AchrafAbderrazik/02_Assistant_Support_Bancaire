"""API REST (FastAPI) et interface web statique.

Le client « connecté » est simulé par le champ customer_id (dans une vraie application, il viendrait du jeton
d'authentification de la session, jamais du texte du message).
"""
from __future__ import annotations

import json
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import DISCLAIMER_FR, __version__
from .config import MAX_MESSAGE_CHARS, Settings
from .service import AssistantService


class ChatRequest(BaseModel):
    customer_id: str = Field(pattern=r"^C\d{3}$", examples=["C001"])
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    conversation_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    lang: Literal["fr", "en"] | None = None


def create_app(settings: Settings | None = None, service: AssistantService | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    svc = service or AssistantService(settings)
    app = FastAPI(title="Assistant de support bancaire (démonstration)", version=__version__, description=DISCLAIMER_FR)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "model": svc.model.meta.get("selected_kind"), "articles": len(svc.kb.articles),
                "generator": svc.settings.llm_backend, "thresholds": {"en_article": svc.en_threshold, "fr": svc.fr_threshold}}

    @app.get("/api/customers")
    def customers():
        return {"customers": svc.tools.customers(), "note": "clients fictifs"}

    @app.post("/api/chat")
    def chat(req: ChatRequest):
        try:
            return svc.chat(req.customer_id, req.message, req.conversation_id, req.lang)
        except LookupError as e:
            raise HTTPException(404, str(e)) from e
        except PermissionError as e:
            raise HTTPException(403, str(e)) from e
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    @app.get("/api/conversations/{conversation_id}")
    def transcript(conversation_id: str, customer_id: str = Query(pattern=r"^C\d{3}$")):
        try:
            svc.store.get_or_create(conversation_id, customer_id)
        except PermissionError as e:
            raise HTTPException(403, str(e)) from e
        return {"conversation_id": conversation_id, "messages": svc.store.transcript(conversation_id)}

    @app.get("/api/cases")
    def cases(limit: int = Query(50, ge=1, le=200)):
        return {"cases": svc.store.cases(limit)}

    @app.get("/api/stats")
    def stats():
        return svc.store.stats()

    @app.get("/api/metrics")
    def metrics():
        path = settings.reports_dir / "metrics.json"
        if not path.exists():
            raise HTTPException(404, "lancer d'abord : python -m assistant evaluate")
        m = json.loads(path.read_text(encoding="utf-8"))
        for k in ("intent", "article"):
            m["banking77_test"][k].pop("risk_coverage", None)
        m["scenarios"].pop("scenarios", None)
        return m

    if settings.ui_dir.exists():
        app.mount("/static", StaticFiles(directory=settings.ui_dir), name="static")

        @app.get("/")
        def index():
            return FileResponse(settings.ui_dir / "index.html")

    return app
