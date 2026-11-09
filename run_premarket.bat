@echo off
rem Pre-market environment update for Task Scheduler (no key press needed).
rem Run on weekdays around 08:30 JST, after the US market has closed.
cd /d "%~dp0"
set PYTHONUTF8=1
if not exist logs mkdir logs
echo ==== %date% %time% ==== >> logs\run_premarket.log
".venv\Scripts\python.exe" run_premarket.py >> logs\run_premarket.log 2>&1
exit /b %errorlevel%
