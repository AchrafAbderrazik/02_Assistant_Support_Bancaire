@echo off
REM Installe, construit, teste puis lance l'assistant (Windows).
cd /d "%~dp0"
python -m venv .venv
call .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
python -m assistant build
python -m pytest -q > reports\test_results.txt
type reports\test_results.txt
python -m assistant serve
