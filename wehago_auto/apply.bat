@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
call "%~dp0_find_python.bat"
if not defined PY call "%~dp0setup.bat" nopause
if not defined PY call "%~dp0_find_python.bat"
if not defined PY (
  echo Python not found. Please run setup.bat first.
  pause
  exit /b 1
)
%PY% -c "import playwright" >nul 2>&1 || %PY% -m pip install -q -r requirements.txt
%PY% run.py apply %*
pause
