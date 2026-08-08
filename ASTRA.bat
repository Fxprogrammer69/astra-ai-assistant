@echo off
title ASTRA Web
cd /d "%~dp0"

echo.
echo  ========================================
echo   ASTRA — web mode (no Electron)
echo  ========================================
echo.

REM Load .env into process env (simple KEY=VAL lines)
if exist "%~dp0.env" (
  for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%~dp0.env") do (
    if not "%%A"=="" set "%%A=%%B"
  )
)

set "PYTHONPATH=%~dp0src\brain;%~dp0src"
set "ASTRA_FAST_MODE=1"
set "ASTRA_ENABLE_CV=0"
set "ASTRA_ENABLE_SPEECH=0"
set "ASTRA_PORT=8787"
set "ASTRA_WS_PORT=8788"

where py >nul 2>&1
if errorlevel 1 (
  where python >nul 2>&1
  if errorlevel 1 (
    echo Python not found. Install Python 3.11+ from python.org
    pause
    exit /b 1
  )
  set "PY=python"
) else (
  set "PY=py -3"
)

echo Checking websockets...
%PY% -c "import websockets" 2>nul
if errorlevel 1 (
  echo Installing websockets...
  %PY% -m pip install websockets --quiet
)

echo Starting brain + UI on http://127.0.0.1:8787
echo Press Ctrl+C to stop.
echo.

%PY% "%~dp0src\brain\webapp.py"
if errorlevel 1 (
  echo.
  echo ASTRA exited with an error.
  pause
)
