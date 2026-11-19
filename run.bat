@echo off
REM Health and Disease Analytics - Windows launcher
cd /d %~dp0
python -c "import flask" 2>nul || pip install -r requirements.txt
echo Starting at http://127.0.0.1:5000  (demo: analyst@demo.mw / Analyst123!)
python app.py
pause
