@echo off
cd /d "%~dp0"
py -3 -c "import PySide6" >nul 2>nul
if errorlevel 1 py -3 -m pip install -r requirements.txt
py -3 -m app.main %*
pause
