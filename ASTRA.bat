@echo off
title ASTRA
cd /d "%~dp0"
echo Starting ASTRA...
if not exist "node_modules\electron" (
  echo Dependencies missing. Running npm install...
  call npm install
  if errorlevel 1 (
    echo npm install failed. Install Node.js LTS and try again.
    pause
    exit /b 1
  )
)
set PYTHONPATH=%~dp0src\brain
if exist "%~dp0.env" (
  for /f "usebackq tokens=1,* delims==" %%A in ("%~dp0.env") do (
    if not "%%A"=="" if not "%%A:~0,1%"=="#" set "%%A=%%B"
  )
)
call npm start
if errorlevel 1 (
  echo ASTRA exited with an error.
  pause
)
