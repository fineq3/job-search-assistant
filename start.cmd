@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Python environment missing. Follow README.md first.
  pause
  exit /b 1
)
if not exist "frontend\dist\index.html" (
  echo Building Vue frontend...
  call npm.cmd --prefix frontend run build
  if errorlevel 1 (
    pause
    exit /b 1
  )
)
echo Open http://127.0.0.1:8000 after Application startup complete.
echo Press Ctrl+C to stop. Keep this window open while using the app.
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
if errorlevel 1 pause
