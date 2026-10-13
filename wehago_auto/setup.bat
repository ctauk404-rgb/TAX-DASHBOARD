@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo  WEHAGO card automation - setup (first time on this PC)
echo ============================================================

rem 1) Unblock files downloaded from the internet (ZIP)
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -LiteralPath '%~dp0' -Recurse | Unblock-File" >nul 2>&1

rem 2) Python
call "%~dp0_find_python.bat"
if defined PY goto :have_python
echo.
echo [1/2] Installing Python 3.12 ...
winget --version >nul 2>&1
if errorlevel 1 goto :no_winget
winget install -e --id Python.Python.3.12 --scope user --accept-source-agreements --accept-package-agreements
call "%~dp0_find_python.bat"
if defined PY goto :have_python
:no_winget
echo.
echo Could not install Python automatically.
echo  1. Open https://www.python.org/downloads/ and install Python
echo  2. On the first screen CHECK "Add python.exe to PATH"
echo  3. Run setup.bat again
start "" https://www.python.org/downloads/
if not "%~1"=="nopause" pause
exit /b 1

:have_python
echo.
echo Python: %PY%
%PY% --version

rem 3) Libraries (Playwright). Uses the Chrome/Edge already on this PC, no browser download.
echo.
echo [2/2] Installing libraries ...
%PY% -m pip install --upgrade pip -q
%PY% -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo Library install failed. Check the internet connection, then run setup.bat again.
  if not "%~1"=="nopause" pause
  exit /b 1
)
echo.
echo ============================================================
echo  Setup complete. You can now run batch.bat / apply.bat etc.
echo ============================================================
if not "%~1"=="nopause" pause
exit /b 0
