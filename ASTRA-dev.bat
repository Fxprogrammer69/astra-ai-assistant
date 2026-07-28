@echo off
title ASTRA (dev)
cd /d "%~dp0"
echo Starting ASTRA (dev mode)...
set PYTHONPATH=%~dp0src\brain
if exist "%~dp0.env" (
  for /f "usebackq tokens=1,* delims==" %%A in ("%~dp0.env") do (
    if not "%%A"=="" if not "%%A:~0,1%"=="#" set "%%A=%%B"
  )
)
call npm run dev
