@echo off
REM Captura os cookies do Firefox local (deixe o Firefox aberto e logado).
setlocal EnableExtensions
cd /d "%~dp0"

set "PYTHON=%CD%\.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo [ERRO] Rode INSTALAR_WINDOWS.bat primeiro.
    pause
    exit /b 1
)

echo ============================================================
echo  Captura de cookies do Projudi
echo  1. Deixe o Firefox aberto e logado no Projudi
echo  2. Este script le o cookies.sqlite (+ WAL) do perfil local
echo ============================================================
echo.

"%PYTHON%" scripts\capture_cookies_windows.py
pause
endlocal
