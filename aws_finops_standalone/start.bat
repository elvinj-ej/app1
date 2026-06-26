@echo off
REM AWS FinOps Tracker — Start Script
REM Runs on http://0.0.0.0:4020/AWSFinOps

cd /d "%~dp0"

REM Install dependencies if needed (comment out after first run)
pip install flask waitress openpyxl werkzeug --quiet

REM Optional overrides — uncomment and edit as needed:
REM set AD_ENABLED=false
REM set AD_DOMAIN=COCHLEAR
REM set AD_GROUP=Domain Users
REM set SECRET_KEY=your-secret-key-here
REM set AWS_DATA_ROOT=C:\AWSFinOps\Data

echo Starting AWS FinOps Tracker on port 4020...
python app.py
pause
