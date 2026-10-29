@echo off
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" "%~dp0app.py"
) else (
    python "%~dp0app.py"
)
if errorlevel 1 pause
