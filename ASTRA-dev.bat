@echo off
title ASTRA (dev)
cd /d "%~dp0"
echo Starting ASTRA (dev mode)...
set "PYTHONPATH=%~dp0src\brain;%~dp0src"
set "ASTRA_HOST=127.0.0.1"
if exist "%~dp0.env" (
  for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%~dp0.env") do (
    if not "%%A"=="" set "%%A=%%B"
  )
)
where py >nul 2>&1
if errorlevel 1 (
  python "%~dp0src\brain\webapp.py"
) else (
  py -3 "%~dp0src\brain\webapp.py"
)
