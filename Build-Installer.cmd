@echo off
setlocal
cd /d "%~dp0"
echo.
echo ==== Building the Game Account Switcher installer ====
echo Needs internet the first time. Takes a few minutes.
echo.
".venv\Scripts\python.exe" -c "import tkinter, psutil" >nul 2>&1
if errorlevel 1 call Setup.cmd
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check "pyinstaller==6.16.0"
if errorlevel 1 goto failed
for /f %%v in ('.venv\Scripts\python.exe -c "import switcher; print(switcher.VERSION)"') do set "VER=%%v"

echo [1/2] Packing the app into ValorantSwitcher.exe ...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --log-level WARN --windowed --onedir --hidden-import PIL.ImageTk --name ValorantSwitcher --icon assets\icon.ico --add-data "assets;assets" main.py
if errorlevel 1 goto failed

echo [2/2] Making the installer ...
call :findiscc
if defined ISCC goto build
echo Installing Inno Setup (free tool that makes Windows installers) ...
winget install --id JRSoftware.InnoSetup --exact --source winget --scope user --accept-package-agreements --accept-source-agreements --disable-interactivity
call :findiscc
if defined ISCC goto build
winget install --id JRSoftware.InnoSetup --exact --source winget --accept-package-agreements --accept-source-agreements --disable-interactivity
call :findiscc
if not defined ISCC goto noiscc

:build
"%ISCC%" /Qp "/DAppVersion=%VER%" installer\ValorantSwitcher.iss
if errorlevel 1 goto failed
echo.
echo DONE:  dist\GameAccountSwitcher-Setup-%VER%.exe
echo That single file is what you give to friends.
echo.
echo Opening the installer window now. Click Next, then Finish.
start "" "%~dp0dist\GameAccountSwitcher-Setup-%VER%.exe"
timeout /t 4 >nul
exit /b 0

:findiscc
set "ISCC="
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
exit /b 0

:noiscc
echo Inno Setup could not be installed automatically.
echo Get it free from https://jrsoftware.org/isdl.php , install it, then run Build-Installer.cmd again.
echo (The app itself was built: dist\ValorantSwitcher\ValorantSwitcher.exe)
pause
exit /b 1

:failed
echo.
echo The build stopped. Read the message above, check your internet connection, and run it again.
pause
exit /b 1
