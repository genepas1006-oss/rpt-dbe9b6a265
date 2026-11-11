@echo off
rem Opening-gap slot (09:25) for Task Scheduler (no key press needed).
cd /d "%~dp0"
rem Pull the latest code first (ignore failures such as being offline).
if not exist logs mkdir logs
git pull --ff-only origin main >> logs\git_pull.log 2>&1
set PYTHONUTF8=1
echo ==== %date% %time% ==== >> logs\run_open.log
".venv\Scripts\python.exe" run_open.py >> logs\run_open.log 2>&1
exit /b %errorlevel%
