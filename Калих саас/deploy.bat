@echo off
REM =========================================================================
REM KALIX Lyceum SaaS — Windows Local & Server Deployment Script
REM =========================================================================
chcp 65001 >nul
echo ==============================================
echo   KALIX Lyceum SaaS — Windows Runner Script
echo ==============================================

if not exist venv (
    echo [1/3] Creating Python virtual environment in .\venv...
    python -m venv venv
)

echo [2/3] Activating virtual environment and installing dependencies...
call venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt

echo [3/3] Launching KALIX SaaS Server on http://127.0.0.1:5000...
python app.py
pause
