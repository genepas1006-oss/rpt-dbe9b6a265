@echo off
rem Manual run of the pre-market environment update. Keeps the window open.
cd /d "%~dp0"
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
echo Updating the pre-market environment (US market -> expected gap)...
".venv\Scripts\python.exe" run_premarket.py > logs\run_premarket_manual.log 2>&1
set RESULT=%errorlevel%
type logs\run_premarket_manual.log
echo.
if "%RESULT%"=="0" (
  echo [DONE] Finished. Log: logs\run_premarket_manual.log
) else (
  echo [ERROR] Failed with exit code %RESULT%. See the messages above. Log: logs\run_premarket_manual.log
)
pause
