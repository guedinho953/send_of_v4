@echo off
REM Para o PostgreSQL local do projeto (porta 5433).
setlocal EnableExtensions
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File scripts\postgres_local_windows.ps1 -Stop
pause
endlocal
