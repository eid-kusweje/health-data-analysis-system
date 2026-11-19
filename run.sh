#!/usr/bin/env bash
# Health and Disease Analytics - Linux/macOS launcher
cd "$(dirname "$0")" || exit 1
python3 -c "import flask" 2>/dev/null || pip3 install -r requirements.txt
echo "Starting at http://127.0.0.1:5000  (demo: analyst@demo.mw / Analyst123!)"
python3 app.py
