@echo off
REM mdhub - unified Markdown conversion tool (mdkit)
REM Usage:
REM   mdhub.bat doctor
REM   mdhub.bat docx input.md
REM   mdhub.bat html input.md
REM   mdhub.bat to-md input.docx
REM   mdhub.bat multi input.md --to docx,html,pdf
REM   mdhub.bat pipe input.docx --to md,docx
REM
REM Prefers the project virtualenv (.venv); falls back to system python.
setlocal
REM Remember the caller's cwd BEFORE cd'ing to the project root, so that a
REM relative input path resolves against the directory the user ran from.
set "MDHUB_CALLER_CWD=%CD%"
cd /d "%~dp0.."
set "ARGS=%*"

set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

"%PY%" -m mdkit %ARGS%
endlocal
