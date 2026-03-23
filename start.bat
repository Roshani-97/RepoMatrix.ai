@echo off
title RepoMatrix.ai Backend
color 0A

echo ========================================
echo   RepoMatrix.ai - Starting Backend
echo ========================================
echo.

cd /d %~dp0backend

if not exist venv (
    echo [1/3] Creating virtual environment...
    python -m venv venv
)

echo [1/3] Activating virtual environment...
call venv\Scripts\activate.bat

echo [2/3] Installing dependencies...
pip install -q flask flask-cors PyGithub python-dotenv requests groq tavily-python e2b-code-interpreter 2>nul

echo [3/3] Starting Flask server...
echo.
echo Server running at: http://localhost:5000
echo Press Ctrl+C to stop
echo.

python app.py

pause
