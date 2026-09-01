@echo off
setlocal

echo ==========================================
echo Setting up backend virtual environment...
echo ==========================================

cd /d "%~dp0bot new backend"

IF NOT EXIST ".venv" (
    echo Creating .venv...
    python -m venv .venv
)

echo Activating .venv and installing backend dependencies...
call .venv\Scripts\activate.bat
pip install -r requirements.txt

echo ==========================================
echo Installing frontend dependencies...
echo ==========================================

cd /d "%~dp0trading-bot-dashboard"

IF NOT EXIST "node_modules" (
    call npm install
)

echo ==========================================
echo Starting backend...
echo ==========================================

start "Backend Server" cmd /k "cd /d ""%~dp0bot new backend"" && call .venv\Scripts\activate.bat && set PYTHONPATH=. && uvicorn src.main:app --reload --host 127.0.0.1 --port 6000"

echo ==========================================
echo Starting frontend...
echo ==========================================

start "Frontend Server" cmd /k "cd /d ""%~dp0trading-bot-dashboard"" && npm run dev"

echo Both servers started 🚀
pause