@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" main.py --gui
) else if exist "python\python.exe" (
  "python\python.exe" main.py --gui
) else (
  echo [WhiteCore] Python bulunamadi. Once venv kurun: python -m venv .venv
  echo Ardindan: .venv\Scripts\pip install -r requirements.txt
  pause
  exit /b 1
)
endlocal
