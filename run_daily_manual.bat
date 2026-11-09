@echo off
rem Manual run of the daily report. Keeps the window open so you can read the result or the error.
rem (Do not use this for Task Scheduler: it waits for a key press. Use run_daily.bat for that.)
cd /d "%~dp0"
rem Pull the latest code first (ignore failures such as being offline).
if not exist logs mkdir logs
git pull --ff-only origin main >> logs\git_pull.log 2>&1
set PYTHONUTF8=1
if not exist logs mkdir logs
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] .venv\Scripts\python.exe was not found. Create the virtual environment first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -c "import yfinance, pandas" 2>nul
if errorlevel 1 (
  echo [ERROR] Required libraries are missing. Run this once, then try again:
  echo   .venv\Scripts\python.exe -m pip install -r requirements.txt
  pause
  exit /b 1
)
echo Running the daily report. This takes a few minutes. Do not close this window...
".venv\Scripts\python.exe" run_daily.py > logs\run_daily_manual.log 2>&1
set RESULT=%errorlevel%
type logs\run_daily_manual.log
echo.
if "%RESULT%"=="0" (
  echo [DONE] Finished. Log: logs\run_daily_manual.log
) else (
  echo [ERROR] Failed with exit code %RESULT%. See the messages above. Log: logs\run_daily_manual.log
)
pause
