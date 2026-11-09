@echo off
cd /d "%~dp0"
rem Pull the latest code first (ignore failures such as being offline).
if not exist logs mkdir logs
git pull --ff-only origin main >> logs\git_pull.log 2>&1
".venv\Scripts\python.exe" run_daily.py
