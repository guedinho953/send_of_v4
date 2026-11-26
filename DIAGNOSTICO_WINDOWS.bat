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

findstr /b /i "DATABASE_URL=postgres" .env >nul 2>&1
if not errorlevel 1 (
    if exist "pgdata\.send_of_local_pg" (
        echo [pg] Verificando PostgreSQL local do projeto...
        powershell -NoProfile -ExecutionPolicy Bypass -File scripts\postgres_local_windows.ps1 >nul
    ) else (
        echo [pg] PostgreSQL externo configurado; usando o servidor existente.
    )
)

"%PYTHON%" manage.py diagnostico_firefox
pause
endlocal
