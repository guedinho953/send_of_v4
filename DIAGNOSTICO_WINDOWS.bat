@echo off
REM Diagnostico do Firefox local, perfil, cookies e Playwright.
setlocal EnableExtensions
cd /d "%~dp0"

set "PYTHON=%CD%\.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo [ERRO] Rode INSTALAR_WINDOWS.bat primeiro.
    pause
    exit /b 1
)

"%PYTHON%" manage.py diagnostico_firefox
pause
endlocal
