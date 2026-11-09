@echo off
setlocal
cd /d "%~dp0"
echo.
echo Game Account Switcher - one-time setup
echo Installs Python 3.12 (if missing) and one small library (psutil). Needs internet once.
echo.
set "PY="
py -3.12 -c "import sys" >nul 2>&1 && set "PY=py -3.12"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe""
if not defined PY (
    where winget >nul 2>&1 || goto nopython
    echo Installing Python 3.12 with winget...
    winget install --id Python.Python.3.12 --exact --source winget --scope user --accept-package-agreements --accept-source-agreements --disable-interactivity
    if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (set "PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe"") else goto nopython
)
if not exist ".venv\Scripts\python.exe" %PY% -m venv .venv || goto failed
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt || goto failed
".venv\Scripts\python.exe" -c "import tkinter, psutil" || goto failed
echo Setup complete.
exit /b 0
:nopython
echo Python 3.12 could not be installed automatically.
echo Install it from https://www.python.org/downloads/windows/ (tick "tcl/tk" and "py launcher"), then run Setup.cmd again.
pause
exit /b 1
:failed
echo Setup failed. Check your internet connection, keep this folder somewhere writable (e.g. Documents), and run Setup.cmd again.
pause
exit /b 1
