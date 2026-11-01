#!/usr/bin/env bash
# Installe, construit, teste puis lance l'assistant (macOS / Linux).
set -euo pipefail
cd "$(dirname "$0")"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
python -m assistant build
python -m pytest -q | tee reports/test_results.txt
python -m assistant serve
