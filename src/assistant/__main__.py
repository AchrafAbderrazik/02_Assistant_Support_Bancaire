"""Interface en ligne de commande.

python -m assistant build      # base simulée + entraînement + évaluation (tout le pipeline)
python -m assistant seed       # (re)crée la base bancaire simulée
python -m assistant train      # entraîne le classifieur et apprend les seuils
python -m assistant evaluate   # évalue et écrit reports/metrics.json + evaluation_report.md
python -m assistant chat       # conversation dans le terminal (client C001 par défaut)
python -m assistant serve      # API + interface web sur http://127.0.0.1:8000
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from .config import Settings


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="assistant", description="Assistant de support bancaire (démonstration)")
    p.add_argument("command", choices=["build", "seed", "train", "evaluate", "chat", "serve"])
    p.add_argument("--customer", default="C001")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s : %(message)s")
    settings = Settings.from_env()
    settings.ensure_dirs()

    if args.command in ("seed", "build"):
        from .bankdb import seed_database
        print("base simulée :", seed_database(settings.bank_db))
        if settings.conv_db.exists():
            settings.conv_db.unlink()
    if args.command in ("train", "build"):
        from .train import train_all
        _, summary = train_all(settings)
        print("modèle :", summary["selected_kind"], "| seuils :", {k: round(summary[k], 3) for k in
              ("intent_threshold", "en_article_threshold", "fr_threshold")}, "| alpha :", summary["hybrid_alpha"])
    if args.command in ("evaluate", "build"):
        from .evaluate import evaluate_all
        m = evaluate_all(settings)
        b = m["banking77_test"]
        print(json.dumps({"intent_accuracy": b["intent"]["accuracy"], "article_accuracy": b["article"]["accuracy_hybrid"],
                          "article_coverage": b["article"]["coverage"], "article_accepted_accuracy": b["article"]["accepted_accuracy"],
                          "fr_test_hit1": m["french"]["test"]["hit1"], "scenarios": f"{m['scenarios']['passed']}/{m['scenarios']['n']}"},
                         indent=2))
    if args.command == "chat":
        from .service import AssistantService
        svc, conv = AssistantService(settings), None
        print("Tapez votre message (Ctrl+C pour quitter).")
        try:
            while True:
                msg = input("> ").strip()
                if not msg:
                    continue
                r = svc.chat(args.customer, msg, conv)
                conv = r["conversation_id"]
                print(f"[{r['action']} | {r['lang']} | article={r['article']['id'] if r['article'] else '-'} | conf={r['confidence']}]")
                print(r["reply"], "\n")
        except (KeyboardInterrupt, EOFError):
            print()
    if args.command == "serve":
        import uvicorn
        from .api import create_app
        uvicorn.run(create_app(settings), host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
