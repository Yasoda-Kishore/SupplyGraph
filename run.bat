@echo off
REM Start SupplyGraph on http://localhost:8000
cd /d %~dp0
if not exist .venv (
  python -m venv .venv
  .venv\Scripts\pip install -r requirements.txt
)
.venv\Scripts\python -m uvicorn backend.app.main:app --reload --port 8000
