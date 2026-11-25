@echo off
REM One-click build for mdhub:
REM   1. create .venv + install Python deps
REM   2. npm install for the Node renderer
REM   3. run doctor to verify the environment
setlocal
cd /d "%~dp0"

echo [1/3] Python venv + deps
rem Prefer Python 3.14: markitdown 0.1.8+ requires Python <3.15 (0.0.2 on 3.15 breaks to-md).
if not exist ".venv\Scripts\python.exe" (
  py -3.14 -m venv .venv 2>nul || python -m venv .venv
)
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
".venv\Scripts\python.exe" -m pip install -r requirements.txt

echo [2/3] Node deps
if exist "node\node_modules\" (
  echo node_modules exists, skipping npm i
) else (
  pushd node
  call npm install
  popd
)

echo [3/3] doctor
".venv\Scripts\python.exe" -m mdkit doctor

echo.
echo build done. try:  bin\mdhub.bat doctor
endlocal
