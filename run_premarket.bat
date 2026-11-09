@echo off
rem Pre-market environment update for Task Scheduler (no key press needed).
rem Run on weekdays around 08:30 JST, after the US market has closed.
cd /d "%~dp0"
rem Pull the latest code first (ignore failures such as being offline).
if not exist logs mkdir logs
git pull --ff-only origin main >> logs\git_pull.log 2>&1
set PYTHONUTF8=1
if not exist logs mkdir logs
echo ==== %date% %time% ==== >> logs\run_premarket.log
".venv\Scripts\python.exe" run_premarket.py >> logs\run_premarket.log 2>&1
exit /b %errorlevel%
