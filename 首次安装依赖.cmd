@echo off
cd /d "%~dp0"
python -m venv "%~dp0.venv"
if errorlevel 1 goto failed
"%~dp0.venv\Scripts\python.exe" -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 goto failed
echo Setup complete. Open the launcher to start the app.
pause
exit /b 0
:failed
echo Setup failed. See README.md for manual setup instructions.
pause
exit /b 1
