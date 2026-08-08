@echo off
title ASTRA Desktop (local PC only)
cd /d "%~dp0"

echo.
echo  ========================================
echo   ASTRA — DESKTOP APP ON THIS PC
echo   Local only: 127.0.0.1 (not the internet)
echo  ========================================
echo.

if exist "%~dp0.env" (
  for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%~dp0.env") do (
    if not "%%A"=="" set "%%A=%%B"
  )
)

set "PYTHONPATH=%~dp0src\brain;%~dp0src"
set "ASTRA_HOST=127.0.0.1"
set "ASTRA_FAST_MODE=1"
set "ASTRA_ENABLE_CV=0"
set "ASTRA_ENABLE_SPEECH=0"
set "ASTRA_PORT=8787"
set "ASTRA_WS_PORT=8788"

where py >nul 2>&1
if errorlevel 1 (
  where python >nul 2>&1
  if errorlevel 1 (
    echo Python not found. Install Python 3 from python.org
    pause
    exit /b 1
  )
  set "PY=python"
) else (
  set "PY=py -3"
)

echo Checking packages...
%PY% -c "import websockets" 2>nul
if errorlevel 1 (
  echo Installing websockets...
  %PY% -m pip install websockets --quiet
)
%PY% -c "import webview" 2>nul
if errorlevel 1 (
  echo Installing pywebview (desktop window)...
  %PY% -m pip install pywebview --quiet
)

echo.
echo Starting ASTRA on THIS computer only...
echo Close the ASTRA window to quit.
echo.

%PY% "%~dp0src\brain\desktop.py"
if errorlevel 1 (
  echo.
  echo ASTRA exited with an error.
  pause
)
