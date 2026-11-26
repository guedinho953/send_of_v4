@echo off
REM ============================================================
REM  send_of_v4 - inicia o Django e abre o Firefox LOCAL
REM ============================================================
setlocal EnableExtensions
cd /d "%~dp0"

set "PYTHON=%CD%\.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo [AVISO] Ambiente .venv nao encontrado. Rodando a instalacao...
    call INSTALAR_WINDOWS.bat
    if not exist "%PYTHON%" exit /b 1
)

"%PYTHON%" manage.py migrate --noinput >nul 2>&1

echo ============================================================
echo  send_of_v4 - servidor em http://127.0.0.1:8000/
echo  Firefox local sera aberto automaticamente.
echo  Deixe esta janela aberta. Ctrl+C encerra o servidor.
echo ============================================================
echo.

start "" /b "%PYTHON%" scripts\abrir_navegador.py http://127.0.0.1:8000/ --delay 3
"%PYTHON%" manage.py runserver 127.0.0.1:8000
endlocal
