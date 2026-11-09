@echo off
setlocal
cd /d "%~dp0"
rem Only run setup when the environment is missing or broken (v2 re-ran it on every start).
".venv\Scripts\python.exe" -c "import tkinter, psutil" >nul 2>&1
if errorlevel 1 (
    call Setup.cmd
    if errorlevel 1 exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "%~dp0main.py"
