@echo off
setlocal
cd /d "%~dp0"
".venv\Scripts\python.exe" -m unittest discover -s tests -v
if errorlevel 1 exit /b 1
call npm.cmd --prefix frontend run build
if errorlevel 1 exit /b 1
echo Verification passed.
